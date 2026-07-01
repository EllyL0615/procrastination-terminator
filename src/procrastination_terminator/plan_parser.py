"""Parse plan.txt and sync it into progress.csv as a set-diff (SPEC §3.1).

Sync identity is the task ``code``. Over today-and-future rows only: a code in
the plan but not the table is added (type judged once, here); a code in the
table but not the plan is deleted; a matching code is left completely untouched.
Pre-today rows never take part.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import time

from . import daytime
from .models import Status, Task, TaskType

# Line-leading markers (SPEC §2): a date header opens a day, a time opens a task.
_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\b")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\b\s*(.*)$")


def _subject(description: str) -> str:
    """A short uppercase tag from the description's first word (SPEC §2).

    Deterministic so a task's ``code`` stays stable across syncs; ``\\w+`` also
    matches CJK, so ``睡觉`` -> ``睡觉`` and ``Game Chap1`` -> ``GAME``.
    """
    match = re.match(r"\w+", description)
    return match.group(0).upper() if match else "TASK"


def _code_clock(start: str, day_start: time) -> str:
    """Time field for a task's ``code`` (SPEC §2, §5).

    Carries a before-day-start hour as 24-27 so the code's ``HHMM`` sorts in
    logical-day order: with a 04:00 day start, ``01:00`` (early morning, the tail of
    the logical day) becomes ``2500``, sorting after the evening's ``2300``. Rows are
    ordered purely by ``code``, so this is what puts an after-midnight task last.
    """
    clock = daytime.parse_clock(start)
    hour = clock.hour + 24 if clock < day_start else clock.hour
    return f"{hour:02d}{clock.minute:02d}"


def parse_plan_text(text: str) -> list[dict[str, str]]:
    """Deterministically extract the task backbone from plan.txt (SPEC §2, §9).

    Only line-leading structure carries meaning: a line starting with a date
    (``MM.DD``) opens a logical day and contributes ONLY its date -- trailing text
    on it (a weekday or a note to self like ``07.01 Game``) is ignored. A line
    starting with a time (``HH:MM``) is a task under the current day; its start time
    and the rest of the line (the description) are taken verbatim. Every other line
    is the user's freeform scribble and is skipped -- task notes are attached later
    by the LLM. A task line before any date header is dropped (no day to attach to).

    Returns raw entries (``date``, ``time``, ``subject``, ``description``); ``type``
    and ``notes`` are filled in by the LLM before :func:`build_tasks` assembles them.
    """
    entries: list[dict[str, str]] = []
    current_date: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        time_match = _TIME_RE.match(line)
        if time_match is not None:
            if current_date is None:
                continue
            hour, minute, rest = time_match.groups()
            description = rest.strip()
            entries.append(
                {
                    "date": current_date,
                    "time": f"{int(hour):02d}:{int(minute):02d}",
                    "subject": _subject(description),
                    "description": description,
                }
            )
            continue
        date_match = _DATE_RE.match(line)
        if date_match is not None:
            month, day = date_match.groups()
            current_date = f"{int(month):02d}.{int(day):02d}"
    return entries


@dataclass
class SyncPlan:
    """The outcome of :func:`diff_sync`.

    ``kept`` holds the *existing* rows (with their runtime state) for matched
    codes -- they are returned for visibility but must not be rewritten. Applying
    the plan is: keep every existing row whose code is not in ``to_delete``, then
    append ``to_add``.
    """

    to_add: list[Task]
    to_delete: list[str]  # codes
    kept: list[Task]


class DuplicateCodeError(ValueError):
    """Raised when plan.txt yields two tasks with the same code (SPEC §3.1, C2)."""

    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        super().__init__(f"duplicate task codes in plan.txt: {', '.join(codes)}")


def find_duplicate_codes(tasks: list[Task]) -> list[str]:
    """Return codes that appear more than once, in first-seen order."""
    counts = Counter(t.code for t in tasks)
    seen: dict[str, None] = {}
    for t in tasks:
        if counts[t.code] > 1:
            seen.setdefault(t.code, None)
    return list(seen)


def build_tasks(entries: list[dict[str, str]], day_start: time = time(4, 0)) -> list[Task]:
    """Assemble Task rows from raw LLM-extracted plan entries (pure).

    Each entry has ``date`` (``MM.DD``), ``time`` (``HH:MM`` start), ``subject``
    (short code), ``description``, and ``type``. Entries are ordered by date then
    *logical-day* time (SPEC §5), so an after-midnight task like ``00:00`` sleep
    sorts to the end of its day, not the start. Each task's ``planned_end`` is the
    next same-day task's start (SPEC §2), and the day's last task ends at its own
    start (it is only a boundary, never nagged). Raises :class:`DuplicateCodeError`
    on a repeated code (SPEC §3.1, C2).
    """
    ordered = sorted(
        entries,
        key=lambda e: (e["date"], daytime.logical_order(daytime.parse_clock(e["time"]), day_start)),
    )
    tasks: list[Task] = []
    for i, entry in enumerate(ordered):
        date, start = entry["date"], entry["time"]
        nxt = ordered[i + 1] if i + 1 < len(ordered) else None
        end = nxt["time"] if nxt is not None and nxt["date"] == date else start
        code = f"{date.replace('.', '')}-{_code_clock(start, day_start)}-{entry['subject']}"
        tasks.append(
            Task(
                code=code,
                date=date,
                planned_start=start,
                planned_end=end,
                description=entry["description"],
                notes=entry.get("notes", ""),
                type=TaskType(entry["type"]),
                status=Status.NOT_STARTED,
            )
        )
    duplicates = find_duplicate_codes(tasks)
    if duplicates:
        raise DuplicateCodeError(duplicates)
    return tasks


def diff_sync(existing: list[Task], parsed: list[Task], today: str) -> SyncPlan:
    """Set-diff by code over today-and-future rows.

    ``today`` is the current logical day's ``date`` value (e.g. ``"03.13"``).
    Rows dated before it are out of scope: never added, deleted, or reported.
    """
    existing_in_scope = {t.code: t for t in existing if t.date >= today}
    parsed_in_scope = {t.code: t for t in parsed if t.date >= today}
    to_add = [t for code, t in parsed_in_scope.items() if code not in existing_in_scope]
    to_delete = [code for code in existing_in_scope if code not in parsed_in_scope]
    kept = [t for code, t in existing_in_scope.items() if code in parsed_in_scope]
    return SyncPlan(to_add=to_add, to_delete=to_delete, kept=kept)
