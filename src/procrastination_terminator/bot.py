"""Discord wiring (SPEC §9).

discord.py carries everything: DM send/receive, the per-minute supervisor poll
(``ext.tasks``), and the day-start / day-end triggers (checked by time inside the
loop, so no APScheduler). This module orchestrates the tested pure pieces
(monitor, store, daytime, tone, plan_parser) and the LLM client.

The supervisor tick and command handlers are integration code exercised against
a live Discord + LLM; the decision logic they call is unit-tested elsewhere.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from pathlib import Path

import discord
from discord.ext import tasks as discord_tasks

from . import daytime, store, tone
from .config import Config, PersonalityGranularity
from .llm import LLMClient
from .models import Personality, Status, Task, TaskType
from .monitor import Action, decide
from .plan_parser import DuplicateCodeError, build_tasks, diff_sync

_AWAITING = "awaiting reply"  # placeholder progress marker (SPEC §3.2 robustness)
_NAGGED_TYPES = (TaskType.STUDY, TaskType.WORK)


def _parse_clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def _md(day: date) -> str:
    return f"{day.month:02d}.{day.day:02d}"


def _now_clock(now: datetime) -> str:
    return now.strftime("%H:%M")


def _apply_edit(task: Task, edit: dict[str, str]) -> None:
    """Apply one LLM ``update`` edit to a task in place (SPEC §6)."""
    if "planned_start" in edit:
        task.planned_start = edit["planned_start"]
    if "planned_end" in edit:
        task.planned_end = edit["planned_end"]
    if "description" in edit:
        task.description = edit["description"]
    if "type" in edit:
        task.type = TaskType(edit["type"])
    if "status" in edit:
        task.status = Status(edit["status"])


class Supervisor(discord.Client):
    """The bot: a per-minute supervisor loop plus DM command handling."""

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.dm_messages = True
        super().__init__(intents=intents)
        self.config = config
        self.llm = LLMClient(config)
        self._last_day_start: date | None = None
        self._last_day_end: date | None = None

    async def setup_hook(self) -> None:
        self.tick.change_interval(seconds=self.config.poll_seconds)
        self.tick.start()

    async def close(self) -> None:
        await self.llm.aclose()
        await super().close()

    # -- the supervisor loop -------------------------------------------------

    @discord_tasks.loop(seconds=60)
    async def tick(self) -> None:
        now = datetime.now(self.config.tz)
        await self._maybe_boundaries(now)
        await self._supervise(now)

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.wait_until_ready()

    async def _supervise(self, now: datetime) -> None:
        today = daytime.logical_day_of(now, self.config.day_start)
        resolved = self._resolve_day(now, today)
        if not resolved:
            return
        last_code = resolved[-1][0].code

        changed: dict[str, Task] = {}
        situations: list[str] = []
        lead: Task | None = None
        lead_delay = timedelta(0)
        for i, (task, start, end) in enumerate(resolved):
            if task.type not in _NAGGED_TYPES:
                continue
            action = monitor_decide(task, now, start, end, is_last=task.code == last_code)
            line = self._apply(task, action, now, changed)
            if line is None:
                continue
            situations.append(line)
            if action is Action.END_CHECK_HANDOFF:
                handoff = self._handoff(resolved, i, last_code, changed)
                if handoff is not None:
                    situations.append(handoff)
            delay = now - start if action_is_nag(action) else timedelta(0)
            if lead is None or delay > lead_delay:
                lead, lead_delay = task, delay

        if situations and lead is not None:
            await self._say(situations, lead, today, intensity=tone.intensity_for(lead_delay))
        if changed:
            store.upsert_changed(self.config.progress_path, list(changed.values()))

    def _resolve_day(self, now: datetime, today: date) -> list[tuple[Task, datetime, datetime]]:
        """Today's tasks with absolute start/end, ordered by start."""
        resolved: list[tuple[Task, datetime, datetime]] = []
        for task in store.load(self.config.progress_path):
            if daytime.date_from_md(task.date, now.date()) != today:
                continue
            try:
                start = daytime.resolve(
                    today, _parse_clock(task.planned_start), self.config.day_start, self.config.tz
                )
                end = daytime.resolve(
                    today, _parse_clock(task.planned_end), self.config.day_start, self.config.tz
                )
            except ValueError:
                continue
            resolved.append((task, start, end))
        resolved.sort(key=lambda row: row[1])
        return resolved

    def _apply(
        self, task: Task, action: Action, now: datetime, changed: dict[str, Task]
    ) -> str | None:
        """Apply a decision's side effects to ``task``; return the message line, if any."""
        if action is Action.NAG_START:
            if task.status is Status.NOT_STARTED:
                task.status = Status.OVERDUE
                changed[task.code] = task
            return f"Nag the user to start '{task.description}' (code {task.code})."
        if action is Action.MIDPOINT_CHECK:
            self._mark_awaiting(task, now)
            changed[task.code] = task
            return f"Check how '{task.description}' is going at its midpoint."
        if action is Action.END_CHECK_HANDOFF:
            self._mark_awaiting(task, now)
            changed[task.code] = task
            return f"Confirm '{task.description}' is wrapping up and hand off to what's next."
        return None

    def _handoff(
        self,
        resolved: list[tuple[Task, datetime, datetime]],
        index: int,
        last_code: str,
        changed: dict[str, Task],
    ) -> str | None:
        """Let the end handoff double as the next task's first nag (SPEC §4.2, A8).

        Only fires when the immediate successor is a nagged, non-last task that is
        still NOT_STARTED -- if it is already overdue/active the monitor covers it,
        so we must not nag it twice.
        """
        if index + 1 >= len(resolved):
            return None
        nxt = resolved[index + 1][0]
        if nxt.code == last_code or nxt.type not in _NAGGED_TYPES:
            return None
        if nxt.status is not Status.NOT_STARTED:
            return None
        nxt.status = Status.OVERDUE
        changed[nxt.code] = nxt
        return f"Then start the next task '{nxt.description}' (code {nxt.code})."

    def _mark_awaiting(self, task: Task, now: datetime) -> None:
        task.latest_progress = _AWAITING
        task.latest_progress_time = now.isoformat()

    # -- day boundaries ------------------------------------------------------

    async def _maybe_boundaries(self, now: datetime) -> None:
        today = now.date()
        if now.time() >= self.config.day_start and self._last_day_start != today:
            self._last_day_start = today
            await self._day_start(now)
        if now.time() >= self.config.day_end and self._last_day_end != today:
            self._last_day_end = today
            await self._day_end(now)

    async def _day_start(self, now: datetime) -> None:
        today_md = _md(daytime.logical_day_of(now, self.config.day_start))
        store.archive_past(self.config.progress_path, self.config.history_path, today_md)
        await self._sync_plan(now)

    async def _day_end(self, now: datetime) -> None:
        today_md = _md(daytime.logical_day_of(now, self.config.day_start))
        tasks = [t for t in store.load(self.config.progress_path) if t.date == today_md]
        done = [t.description for t in tasks if t.status is Status.COMPLETED]
        pending = [
            t.description
            for t in tasks
            if t.type in _NAGGED_TYPES and t.status is not Status.COMPLETED
        ]
        situation = (
            f"Give a brief end-of-day summary. Completed: {done or 'none'}. "
            f"Not finished: {pending or 'none'}. Then nag the user to write tomorrow's plan."
        )
        await self._say([situation], None, daytime.logical_day_of(now, self.config.day_start))

    async def _sync_plan(self, now: datetime) -> None:
        plan_file = Path(self.config.plan_path)
        text = plan_file.read_text(encoding="utf-8") if plan_file.exists() else ""
        try:
            parsed = build_tasks(await self.llm.parse_plan(text))
        except DuplicateCodeError as exc:
            await self._dm(f"plan.txt has duplicate codes: {', '.join(exc.codes)} -- please fix.")
            return
        existing = store.load(self.config.progress_path)
        plan = diff_sync(existing, parsed, _md(daytime.logical_day_of(now, self.config.day_start)))
        if not plan.to_add and not plan.to_delete:
            return
        removed = set(plan.to_delete)
        store.write_all(
            self.config.progress_path,
            [t for t in existing if t.code not in removed] + plan.to_add,
        )

    # -- incoming messages ---------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id != self.config.discord_user_id or message.guild is not None:
            return  # only the owner, only in DMs
        content = message.content.strip()
        if content.startswith("!"):
            head, _, arg = content[1:].partition(" ")
            await self._command(head.lower(), arg.strip())
        else:
            await self._free_chat(content)

    async def _command(self, name: str, arg: str) -> None:
        if name == "started":
            await self._mark(arg, Status.IN_PROGRESS)
        elif name == "completed":
            await self._mark(arg, Status.COMPLETED)
        elif name == "sync":
            await self._sync_plan(datetime.now(self.config.tz))
            await self._dm("Synced plan.txt into progress.csv.")
        elif name == "progress":
            await self._dm(self._render_table())
        elif name == "modify":
            await self._modify(arg)
        else:
            await self._dm(f"Unknown command: !{name}")

    async def _mark(self, fuzzy: str, status: Status) -> None:
        tasks = store.load(self.config.progress_path)
        active = [t for t in tasks if t.type in _NAGGED_TYPES and t.status is not Status.COMPLETED]
        match = await self.llm.match_code(active, fuzzy)
        if match is None:
            await self._dm("Which task do you mean? Try `!started <code>` / `!completed <code>`.")
            return
        now = datetime.now(self.config.tz)
        if status is Status.IN_PROGRESS:
            match.status = Status.IN_PROGRESS
            match.actual_start = _now_clock(now)
            match.latest_progress_time = now.isoformat()
        else:
            match.status = Status.COMPLETED
            match.actual_end = _now_clock(now)
        store.upsert_changed(self.config.progress_path, [match])
        await self._dm(f"Marked '{match.description}' as {status.value}.")

    async def _free_chat(self, content: str) -> None:
        """Plain chat; for a single active task, let the LLM advance its state (SPEC §6, B2)."""
        tasks = store.load(self.config.progress_path)
        active = [t for t in tasks if t.type in _NAGGED_TYPES and t.status is not Status.COMPLETED]
        if len(active) == 1:
            await self._maybe_advance(active[0], content)
        situation = f"The user said: {content!r}. Reply conversationally, grounded in their plan."
        await self._say(
            [situation], active[0] if active else None, datetime.now(self.config.tz).date()
        )

    async def _modify(self, instruction: str) -> None:
        """Let the LLM edit progress.csv from a natural-language instruction (SPEC §6)."""
        if not instruction:
            await self._dm("Tell me what to change, e.g. `!modify move RUN to 19:00`.")
            return
        tasks = store.load(self.config.progress_path)
        by_code = {t.code: t for t in tasks}
        deleted: set[str] = set()
        touched: list[Task] = []
        try:
            for edit in await self.llm.plan_edits(tasks, instruction):
                task = by_code.get(edit.get("code", ""))
                if task is None:
                    continue
                if edit.get("op") == "delete":
                    deleted.add(task.code)
                elif edit.get("op") == "update":
                    _apply_edit(task, edit)
                    touched.append(task)
        except ValueError as exc:
            await self._dm(f"Could not apply that edit: {exc}")
            return
        if deleted:
            kept = [t for t in tasks if t.code not in deleted]
            store.write_all(self.config.progress_path, kept)
        elif touched:
            store.upsert_changed(self.config.progress_path, touched)
        await self._dm(f"Applied {len(touched)} update(s) and {len(deleted)} deletion(s).")

    async def _maybe_advance(self, task: Task, content: str) -> None:
        now = datetime.now(self.config.tz)
        if task.status is Status.OVERDUE and await self.llm.judge_started(task, content):
            task.status = Status.IN_PROGRESS
            task.actual_start = _now_clock(now)
            task.latest_progress_time = now.isoformat()
            store.upsert_changed(self.config.progress_path, [task])
        elif task.status is Status.IN_PROGRESS and await self.llm.judge_completed(task, content):
            task.status = Status.COMPLETED
            task.actual_end = _now_clock(now)
            store.upsert_changed(self.config.progress_path, [task])

    def _render_table(self) -> str:
        rows = store.load(self.config.progress_path)
        if not rows:
            return "progress.csv is empty."
        lines = [f"{t.code}  {t.status.value:<12}  {t.description}" for t in rows]
        return "```\n" + "\n".join(lines) + "\n```"

    # -- outgoing ------------------------------------------------------------

    async def _say(
        self, situations: list[str], lead: Task | None, day: date, *, intensity: int = 0
    ) -> None:
        personality = self._personality(lead, day)
        text = await self.llm.generate_message(
            " ".join(situations), personality=personality, intensity=intensity
        )
        await self._dm(text)

    def _personality(self, task: Task | None, day: date) -> Personality:
        if self.config.personality_granularity is PersonalityGranularity.PER_MESSAGE:
            return random.choice(list(Personality))
        if task is None:
            return tone.fixed_personality(_md(day))
        return tone.personality_for(
            self.config.personality_granularity, code=task.code, day=_md(day)
        )

    async def _dm(self, text: str) -> None:
        user = self.get_user(self.config.discord_user_id) or await self.fetch_user(
            self.config.discord_user_id
        )
        await user.send(text)


def monitor_decide(
    task: Task, now: datetime, start: datetime, end: datetime, *, is_last: bool
) -> Action:
    return decide(
        task,
        now,
        planned_start=start,
        planned_end=end,
        midpoint=daytime.midpoint(start, end),
        is_last_task=is_last,
    )


def action_is_nag(action: Action) -> bool:
    return action is Action.NAG_START


def run(config: Config) -> None:
    """Build and run the bot until disconnected."""
    Supervisor(config).run(config.discord_token)
