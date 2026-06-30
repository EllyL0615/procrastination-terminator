"""Parse plan.txt and sync it into progress.csv as a set-diff (SPEC §3.1).

Sync identity is the task ``code``. Over today-and-future rows only: a code in
the plan but not the table is added (type judged once, here); a code in the
table but not the plan is deleted; a matching code is left completely untouched.
Pre-today rows never take part.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .models import Task


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


def parse(text: str) -> list[Task]:
    """Parse plan.txt into tasks (types judged by the LLM).

    Raises :class:`DuplicateCodeError` if two tasks resolve to the same code --
    that means a typo in plan.txt, and the bot should ask the user to fix it.
    """
    raise NotImplementedError


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
