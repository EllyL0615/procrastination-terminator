"""Parse plan.txt and sync it into progress.csv as a set-diff (SPEC §3.1).

Sync identity is the task ``code``. Over today-and-future rows only: a code in
the plan but not the table is added (type judged once, here); a code in the
table but not the plan is deleted; a matching code is left completely untouched.
Pre-today rows never take part.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Task


@dataclass
class SyncPlan:
    """The outcome of :func:`diff_sync`."""

    to_add: list[Task]
    to_delete: list[str]  # codes
    kept: list[Task]


def parse(text: str) -> list[Task]:
    """Parse plan.txt into tasks (types judged by the LLM).

    Raises if two tasks resolve to the same code -- that means a typo in
    plan.txt, and the bot should ask the user to fix it (SPEC §3.1, C2).
    """
    raise NotImplementedError


def diff_sync(existing: list[Task], parsed: list[Task]) -> SyncPlan:
    """Compute the add/delete/keep set-diff by code over today+future rows."""
    raise NotImplementedError
