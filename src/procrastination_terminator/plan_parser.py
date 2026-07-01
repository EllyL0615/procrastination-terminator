"""Parse plan.txt and sync it into progress.csv as a set-diff (SPEC §3.1).

Sync identity is the task ``code``. Over today-and-future rows only: a code in
the plan but not the table is added (type judged once, here); a code in the
table but not the plan is deleted; a matching code is left completely untouched.
Pre-today rows never take part.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import time

from . import daytime
from .models import Status, Task, TaskType


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
        code = f"{date.replace('.', '')}-{start.replace(':', '')}-{entry['subject']}"
        tasks.append(
            Task(
                code=code,
                date=date,
                planned_start=start,
                planned_end=end,
                description=entry["description"],
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
