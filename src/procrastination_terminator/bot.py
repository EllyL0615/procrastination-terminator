"""Discord wiring (SPEC §9).

discord.py carries everything: channel send/receive, the per-minute supervisor poll
(``ext.tasks``), and the day-start / day-end triggers (checked by time inside the
loop, so no APScheduler). This module orchestrates the tested pure pieces
(monitor, store, daytime, tone, plan_parser) and the LLM client.

The supervisor tick and command handlers are integration code exercised against
a live Discord + LLM; the decision logic they call is unit-tested elsewhere.
"""

from __future__ import annotations

import random
import re
import unicodedata
from datetime import date, datetime, time, timedelta

import discord
from discord.ext import tasks as discord_tasks

from . import daytime, tone
from .config import Config, PersonalityGranularity
from .llm import LLMClient
from .models import Personality, Status, Task, TaskType
from .monitor import Action, decide
from .plan_parser import DuplicateCodeError, build_tasks, diff_sync, parse_plan_text
from .storage import StorageBackend, build_backend

_AWAITING = "awaiting reply"  # placeholder progress marker (SPEC §3.2 robustness)
_NAGGED_TYPES = (TaskType.STUDY, TaskType.WORK)

# ---- !progress table layout (SPEC §6) -- tweak these to change the display ----
# Max display width of each column: the task name in column 1, and the progress
# text in column 2. Longer text is truncated with "…". Bump these to show more.
_TASK_WIDTH = 18
_PROGRESS_WIDTH = 22

# Status shown as an emoji in column 1. All four are East-Asian "wide" (display
# width 2), so the time/task columns after them stay aligned whatever the status.
_STATUS_EMOJI = {
    Status.NOT_STARTED: "⬜",
    Status.OVERDUE: "🟥",
    Status.IN_PROGRESS: "🟨",
    Status.COMPLETED: "✅",
}

_DISCORD_LIMIT = 2000  # max characters per message
_TRUNCATE_MARK = "…"  # single-column per _disp_width (East-Asian "ambiguous"), and
# Discord's monospace code block renders it narrow, so alignment still holds


def _disp_width(text: str) -> int:
    """Monospace display width: East-Asian wide/fullwidth glyphs occupy two columns."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in text)


def _fit(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` display columns (``…`` if cut), then right-pad.

    ``text`` is NFKC-normalized first, folding fullwidth punctuation (fullwidth parens,
    colon, etc.) to their ASCII forms: many monospace fonts draw fullwidth *punctuation*
    narrower than a full CJK cell, which knocks the columns out of alignment even though
    its Unicode width is 2. After folding, only reliably-1 (ASCII) and reliably-2 (CJK)
    glyphs remain. Alignment is by display width, not code points, so CJK task names line
    up inside a monospace code block -- Discord won't render a real markdown table (§6).
    """
    text = unicodedata.normalize("NFKC", text).replace("\n", " ")
    out, used, truncated = "", 0, False
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > width:
            truncated = True
            break
        out, used = out + ch, used + w
    if truncated:
        while used > width - 1:  # free one column for the truncation mark
            out, used = out[:-1], used - _disp_width(out[-1])
        out = out.rstrip(" ")  # no dangling space before the mark
        out, used = out + _TRUNCATE_MARK, _disp_width(out) + 1
    return out + " " * (width - used)


def _parse_clock(value: str) -> time:
    return daytime.parse_clock(value)


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


def _with_notes(line: str, task: Task) -> str:
    """Append the task's plan notes (if any) to a situation line (SPEC §2, §4.1).

    The notes say what this task actually involves, so they ground the concrete
    first step and the progress check instead of the model guessing.
    """
    return f"{line} (Task notes from the plan: {task.notes}.)" if task.notes else line


# ADHD "how to start" breakdown; shared by the start-nag's first nudge and !whattodo.
_STEP_BREAKDOWN = (
    "a concrete, practical way to switch in and begin, broken into 3 to 5 tiny "
    "do-it-now steps (no more than 5), each achievable."
)


def _start_nag_line(task: Task, *, first: bool) -> str:
    """Situation text for a start-nag (SPEC §4.1).

    The user has ADHD and struggles to initiate/switch tasks, so every start-nag --
    whatever the persona -- gives one concrete first action and asks them to report
    back once they've started. The first nag also adds a practical way to switch in
    and begin, broken into 3-5 tiny steps (a concrete count, since "keep it short" is
    too vague for the model to act on); later nags stay light and just help them take
    that first step. Wording is grounded in the recent conversation by
    ``generate_message``, so a correction the user made about the task is honored here.
    """
    line = (
        f"Nag the user to start '{task.description}' (code {task.code}). "
        "They have ADHD and find it hard to begin, so give one concrete, doable first "
        "action and ask them to report back once they've started."
    )
    if first:
        line += " First nudge: also give " + _STEP_BREAKDOWN
    else:
        line += " Keep it brief -- just help them take that first step."
    return _with_notes(line, task)


class Supervisor(discord.Client):
    """The bot: a per-minute supervisor loop plus channel command handling."""

    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()  # includes guild_messages
        intents.message_content = True
        super().__init__(intents=intents)
        self.config = config
        self.store: StorageBackend = build_backend(config)
        self.llm = LLMClient(config, context_provider=self.store.current_context)
        self._last_day_start: date | None = None
        self._last_day_end: date | None = None

    async def setup_hook(self) -> None:
        await self.store.refresh_context()  # prime the standing-context cache (SPEC §2)
        self.tick.change_interval(seconds=self.config.poll_seconds)
        self.tick.start()

    async def close(self) -> None:
        await self.llm.aclose()
        await self.store.aclose()
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
        resolved = await self._resolve_day(now, today)
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
            await self.store.upsert_changed(list(changed.values()))

    async def _resolve_day(
        self, now: datetime, today: date
    ) -> list[tuple[Task, datetime, datetime]]:
        """Today's tasks with absolute start/end, ordered by start."""
        resolved: list[tuple[Task, datetime, datetime]] = []
        for task in await self.store.load_progress():
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
        resolved.sort(key=lambda row: row[0].code)  # code encodes logical-day order (SPEC §2)
        return resolved

    def _apply(
        self, task: Task, action: Action, now: datetime, changed: dict[str, Task]
    ) -> str | None:
        """Apply a decision's side effects to ``task``; return the message line, if any."""
        if action is Action.NAG_START:
            first = task.status is Status.NOT_STARTED  # this tick is its very first nag
            if first:
                task.status = Status.OVERDUE
                changed[task.code] = task
            return _start_nag_line(task, first=first)
        if action is Action.MIDPOINT_CHECK:
            self._mark_awaiting(task, now)
            changed[task.code] = task
            return _with_notes(f"Check how '{task.description}' is going at its midpoint.", task)
        if action is Action.END_CHECK_HANDOFF:
            self._mark_awaiting(task, now)
            changed[task.code] = task
            return _with_notes(
                f"Confirm '{task.description}' is wrapping up and hand off to what's next.", task
            )
        if action is Action.STOP_NAGGING and task.status is Status.NOT_STARTED:
            # Window fully missed before we ever nagged it: record it as unstarted
            # (overdue) for the day-end summary, silently -- no message (SPEC §3.2).
            task.status = Status.OVERDUE
            changed[task.code] = task
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
        # The handoff doubles as the next task's first nag, so give it the full
        # start guidance (SPEC §4.1, §4.2).
        return "Then get them onto the next task. " + _start_nag_line(nxt, first=True)

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
        await self.store.refresh_context()  # once a day is enough for standing context
        today_md = _md(daytime.logical_day_of(now, self.config.day_start))
        await self.store.archive_past(today_md)
        await self._sync_plan(now)

    async def _day_end(self, now: datetime) -> None:
        today_md = _md(daytime.logical_day_of(now, self.config.day_start))
        tasks = [t for t in await self.store.load_progress() if t.date == today_md]
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

    async def _sync_plan(self, now: datetime) -> bool:
        """Sync plan.txt into progress.csv; return False only if it bailed on an error."""
        text = await self.store.read_plan()
        entries = parse_plan_text(text)  # deterministic backbone (SPEC §2)
        if entries:
            annotations = await self.llm.annotate_plan(text, entries)
            for entry, annotation in zip(entries, annotations, strict=True):
                entry.update(annotation)  # type + notes onto the fixed task
        try:
            parsed = build_tasks(entries, self.config.day_start)
        except DuplicateCodeError as exc:
            await self._send(f"plan.txt has duplicate codes: {', '.join(exc.codes)} -- please fix.")
            return False
        today = _md(daytime.logical_day_of(now, self.config.day_start))
        existing = await self.store.load_progress()
        plan = diff_sync(existing, parsed, today)
        # plan.txt owns the notes column: refresh it on matched rows too, leaving all
        # runtime state untouched -- the one exception to "matched rows stay" (SPEC §3.1).
        parsed_notes = {t.code: t.notes for t in parsed if t.date >= today}
        notes_changed = False
        for task in existing:
            fresh = parsed_notes.get(task.code)
            if fresh is not None and task.notes != fresh:
                task.notes = fresh
                notes_changed = True
        if not plan.to_add and not plan.to_delete and not notes_changed:
            return True
        removed = set(plan.to_delete)
        await self.store.write_all([t for t in existing if t.code not in removed] + plan.to_add)
        return True

    # -- incoming messages ---------------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        if (
            message.author.id != self.config.discord_user_id
            or message.channel.id != self.config.discord_channel_id
        ):
            return  # only the owner, only in the bot's channel
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
            if await self._sync_plan(datetime.now(self.config.tz)):
                await self._send("Synced plan.txt into progress.csv.")
                await self._show_progress()  # show the result, else it is invisible
        elif name == "progress":
            await self._show_progress(detailed=arg.lower() == "detailed")
        elif name == "whattodo":
            await self._whattodo(arg)
        elif name == "modify":
            await self._modify(arg)
        elif name == "clear":
            await self._clear(arg)
        elif name == "reloadcontext":
            await self._reload_context()
        elif name == "tick":
            await self._debug_tick(arg)
        else:
            await self._send(f"Unknown command: !{name}")

    async def _mark(self, fuzzy: str, status: Status) -> None:
        tasks = await self.store.load_progress()
        active = [t for t in tasks if t.type in _NAGGED_TYPES and t.status is not Status.COMPLETED]
        match = await self.llm.match_code(active, fuzzy)
        if match is None:
            await self._send("Which task do you mean? Try `!started <code>` / `!completed <code>`.")
            return
        now = datetime.now(self.config.tz)
        if status is Status.IN_PROGRESS:
            match.status = Status.IN_PROGRESS
            match.actual_start = _now_clock(now)
            match.latest_progress_time = now.isoformat()
        else:
            match.status = Status.COMPLETED
            match.actual_end = _now_clock(now)
        await self.store.upsert_changed([match])
        await self._send(f"Marked '{match.description}' as {status.value}.")

    async def _whattodo(self, fuzzy: str) -> None:
        """Break a task into 3-5 do-it-now steps on demand (SPEC §6).

        No argument -> the task whose window contains now; a fuzzy code -> the
        matching study/work task. It reuses the start-nag's step breakdown (SPEC
        §4.1) but is user-triggered and read-only -- it changes no file.
        """
        now = datetime.now(self.config.tz)
        today = daytime.logical_day_of(now, self.config.day_start)
        if fuzzy:
            tasks = [t for t in await self.store.load_progress() if t.type in _NAGGED_TYPES]
            task = await self.llm.match_code(tasks, fuzzy)
            if task is None:
                await self._send("Which task do you mean? Try `!whattodo <code>`.")
                return
        else:
            task = await self._current_task(now, today)
            if task is None:
                await self._send(
                    "No study/work task is active right now -- name one: `!whattodo <code>`."
                )
                return
        situation = _with_notes(
            f"The user asked how to get started on '{task.description}' (code {task.code}). "
            "They have ADHD and find it hard to begin, so give " + _STEP_BREAKDOWN,
            task,
        )
        await self._say([situation], task, today)

    async def _current_task(self, now: datetime, today: date) -> Task | None:
        """The nagged task whose planned window contains ``now``, if any (SPEC §4.1)."""
        for task, start, end in await self._resolve_day(now, today):
            if task.type in _NAGGED_TYPES and start <= now < end:
                return task
        return None

    async def _live_candidates(self, now: datetime) -> list[Task]:
        """Study/work tasks a free-chat reply could be about right now (SPEC §4.4).

        A task is a candidate while it is overdue or in_progress AND either still in
        its window (``now`` before its planned end) or still awaiting a reply to a
        check we sent -- the latter keeps a just-past-end task in play so a late reply
        to its end-check is not dropped. A task past its end whose check was already
        answered is parked until the day-end summary and no longer competes (this is
        why an earlier task stops being a candidate once you move on to the next).
        not_started and completed tasks are never candidates.
        """
        today = daytime.logical_day_of(now, self.config.day_start)
        candidates: list[Task] = []
        for task, _start, end in await self._resolve_day(now, today):
            if task.type not in _NAGGED_TYPES or task.status not in (
                Status.OVERDUE,
                Status.IN_PROGRESS,
            ):
                continue
            if now < end or task.latest_progress == _AWAITING:
                candidates.append(task)
        return candidates

    async def _free_chat(self, content: str) -> None:
        """Plain chat; attribute the reply to the live task and advance it (SPEC §6, §4.4).

        One live task -> advance it (start / record progress / complete). Several ->
        match the reply to one; if it stays ambiguous, ask rather than guess. None ->
        pure chat.
        """
        now = datetime.now(self.config.tz)
        candidates = await self._live_candidates(now)
        target: Task | None = candidates[0] if len(candidates) == 1 else None
        if len(candidates) > 1:
            target = await self.llm.match_code(candidates, content)
            if target is None:
                await self._send(
                    "Several tasks are active — which one do you mean? "
                    "Use `!started <code>` / `!completed <code>` to be specific."
                )
                return
        if target is not None:
            await self._maybe_advance(target, content)
        situation = f"The user said: {content!r}. Reply conversationally, grounded in their plan."
        await self._say([situation], target, now.date())

    async def _modify(self, instruction: str) -> None:
        """Let the LLM edit progress.csv from a natural-language instruction (SPEC §6)."""
        if not instruction:
            await self._send("Tell me what to change, e.g. `!modify move RUN to 19:00`.")
            return
        tasks = await self.store.load_progress()
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
            await self._send(f"Could not apply that edit: {exc}")
            return
        if deleted:
            kept = [t for t in tasks if t.code not in deleted]
            await self.store.write_all(kept)
        elif touched:
            await self.store.upsert_changed(touched)
        await self._send(f"Applied {len(touched)} update(s) and {len(deleted)} deletion(s).")

    async def _reload_context(self) -> None:
        """Reload the standing context (glossary/tone) from its source (SPEC §2, §4.5).

        The context is cached and normally refreshed only at startup / day-start; this
        lets the user apply an edit immediately. A no-op for the file backend, which
        reads the file live on every message.
        """
        await self.store.refresh_context()
        await self._send("Reloaded context.")

    async def _clear(self, arg: str) -> None:
        """Delete the bot's own messages in the channel (SPEC §6).

        Filters by author, so this only removes the bot's own messages and never
        the user's (deleting theirs would need Manage Messages, which the bot is
        not granted; the user can delete anything manually in the channel). Scope
        by arg:
        empty -> the most recent bot message; ``N`` -> the most recent N bot
        messages; ``30m`` / ``2h`` / ``1d`` -> bot messages sent within that
        recent window; ``all`` -> every bot message.
        """
        me = self.user
        if me is None:  # not logged in yet; nothing sensible to do
            return
        channel = await self._channel()
        spec = arg.strip().lower()

        to_delete: list[discord.Message] = []
        if spec == "all":
            async for message in channel.history(limit=None):
                if message.author.id == me.id:
                    to_delete.append(message)
        elif spec == "" or spec.isdigit():
            want = int(spec) if spec else 1
            if want <= 0:
                await self._send("!clear <N> needs a positive count.")
                return
            async for message in channel.history(limit=None):
                if message.author.id == me.id:
                    to_delete.append(message)
                    if len(to_delete) >= want:
                        break
        else:
            match = re.fullmatch(r"(\d+)([mhd])", spec)
            if match is None:
                await self._send(
                    "Usage: !clear (last one) / !clear <N> / !clear <30m|2h|1d> / !clear all."
                )
                return
            amount = int(match.group(1))
            unit = match.group(2)
            delta = {
                "m": timedelta(minutes=amount),
                "h": timedelta(hours=amount),
                "d": timedelta(days=amount),
            }[unit]
            cutoff = datetime.now(self.config.tz) - delta
            async for message in channel.history(limit=None, after=cutoff):
                if message.author.id == me.id:
                    to_delete.append(message)

        for message in to_delete:
            await message.delete()
        await self._send(f"Deleted {len(to_delete)} of my own message(s).")

    async def _debug_tick(self, arg: str) -> None:
        """Debug aid: run one supervisor tick now, or at a simulated ``HH:MM`` today.

        Mirrors the real per-minute loop (boundaries + supervise) so nagging,
        midpoint/end checks and the day-start/day-end triggers can be exercised
        without waiting for the wall clock. Not in the SPEC; remove once testing is
        done. It shares the loop's real side effects: a simulated 04:00 archives and
        syncs, and firing a boundary marks it done for that calendar day.
        """
        now = datetime.now(self.config.tz)
        if arg:
            try:
                clock = _parse_clock(arg)
            except ValueError:
                await self._send("Usage: !tick [HH:MM] (omit the time to tick at now).")
                return
            now = now.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
        await self._maybe_boundaries(now)
        await self._supervise(now)
        await self._send(f"Ticked at {now:%Y-%m-%d %H:%M %Z}.")

    async def _maybe_advance(self, task: Task, content: str) -> None:
        now = datetime.now(self.config.tz)
        if task.status is Status.OVERDUE:
            if await self.llm.judge_started(task, content):
                task.status = Status.IN_PROGRESS
                task.actual_start = _now_clock(now)
                task.latest_progress_time = now.isoformat()
                await self.store.upsert_changed([task])
        elif task.status is Status.IN_PROGRESS:
            kind = await self.llm.classify_progress_reply(task, content)
            if kind == "completed":
                task.status = Status.COMPLETED
                task.actual_end = _now_clock(now)
            elif kind == "progress":
                # A real progress update: record it, replacing the "awaiting reply"
                # placeholder and refreshing the dedup timestamp (SPEC §4.2).
                task.latest_progress = await self.llm.condense_progress(content)
                task.latest_progress_time = now.isoformat()
            else:
                return  # off-topic chat: leave the file untouched (SPEC §6)
            await self.store.upsert_changed([task])

    async def _show_progress(self, *, detailed: bool = False) -> None:
        """Send the rendered progress.csv table (SPEC §6); shared by !progress and !sync."""
        for chunk in await self._render_table(detailed):
            await self._send(chunk)

    async def _render_table(self, detailed: bool) -> list[str]:
        """Render progress.csv as an aligned monospace table, split to fit Discord's limit.

        The first column is ``emoji start-time task`` (status shown as an emoji, task
        padded to a fixed width so the columns line up). When ``detailed`` is set (the
        ``!progress detailed`` form), a second column ``# latest_progress`` is added,
        omitted per-row when that row has no progress; the bare ``!progress`` drops it
        entirely. Returns one or more fenced code blocks -- Discord does not render
        markdown tables, so the code fence keeps the monospace columns aligned (SPEC §6).
        """
        rows = await self.store.load_progress()
        if not rows:
            return ["progress.csv is empty."]
        # Group by day, each day led by its date on its own line (rows are stored
        # day-sorted; the date column was dropped from the rows themselves).
        body: list[str] = []
        prev_date: str | None = None
        for t in rows:
            if t.date != prev_date:
                body.append(t.date)
            body.append(self._table_row(t, detailed))
            prev_date = t.date
        # Pack lines into fenced blocks under the char limit.
        overhead = len("```\n\n```\n") + 1
        chunks: list[str] = []
        batch: list[str] = []
        size = 0
        for line in body:
            if batch and overhead + size + len(line) + 1 > _DISCORD_LIMIT:
                chunks.append(self._fence(batch))
                batch, size = [], 0
            batch.append(line)
            size += len(line) + 1
        if batch:
            chunks.append(self._fence(batch))
        return chunks

    def _table_row(self, t: Task, detailed: bool) -> str:
        first = f"{_STATUS_EMOJI[t.status]} {t.planned_start}  {_fit(t.description, _TASK_WIDTH)}"
        progress = (t.latest_progress or "").strip()
        if not detailed or not progress:
            return first
        # Last column, so cap it at a max width but drop the padding _fit adds.
        return f"{first}  # {_fit(progress, _PROGRESS_WIDTH).rstrip()}"

    @staticmethod
    def _fence(lines: list[str]) -> str:
        return "```\n" + "\n".join(lines) + "\n```"

    # -- outgoing ------------------------------------------------------------

    async def _say(
        self, situations: list[str], lead: Task | None, day: date, *, intensity: int = 0
    ) -> None:
        personality = self._personality(lead, day)
        history = await self._recent_dialogue()
        text = await self.llm.generate_message(
            " ".join(situations), personality=personality, intensity=intensity, history=history
        )
        await self._send(text, mention=True)

    def _personality(self, task: Task | None, day: date) -> Personality:
        if self.config.personality_granularity is PersonalityGranularity.PER_MESSAGE:
            return random.choice(list(Personality))
        if task is None:
            return tone.fixed_personality(_md(day))
        return tone.personality_for(
            self.config.personality_granularity, code=task.code, day=_md(day)
        )

    async def _channel(self) -> discord.abc.Messageable:
        channel = self.get_channel(self.config.discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.config.discord_channel_id)
        if not isinstance(channel, discord.abc.Messageable):
            raise RuntimeError(
                f"DISCORD_CHANNEL_ID {self.config.discord_channel_id} is not a text channel"
            )
        return channel

    async def _recent_dialogue(self) -> list[dict[str, str]]:
        """Recent channel turns (oldest first) as chat messages, so generated wording can
        honor the user's in-conversation corrections. This grounds *wording* only; the
        monitor's decisions stay file+time based and memoryless (SPEC §3.2, §4.5). How
        many turns is ``config.dialogue_history_limit`` (env ``DIALOGUE_HISTORY``).

        Each turn's send time is stamped into its ``content`` as a ``[MM-DD HH:MM]``
        prefix -- the chat API carries only role/content, so the timestamp rides along
        in the text. Times are converted from Discord's UTC ``created_at`` into
        ``config.tz`` (same clock as the logical day) so the LLM reads them in the
        user's timezone. This is wording context only: these timestamps must never
        reach the monitor, whose timing stays snapshot+clock based (memoryless,
        SPEC §3.2).
        """
        channel = await self._channel()
        turns: list[dict[str, str]] = []
        async for message in channel.history(limit=self.config.dialogue_history_limit):
            content = message.content.strip()
            if not content:
                continue
            role = "user" if message.author.id == self.config.discord_user_id else "assistant"
            stamp = message.created_at.astimezone(self.config.tz).strftime("%m-%d %H:%M")
            turns.append({"role": role, "content": f"[{stamp}] {content}"})
        turns.reverse()
        return turns

    async def _send(self, text: str, *, mention: bool = False) -> None:
        channel = await self._channel()
        if mention:  # channels default to notifying only on @mention, so ping to nag
            text = f"<@{self.config.discord_user_id}>\n{text}"
        await channel.send(text)


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
