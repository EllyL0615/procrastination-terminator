"""The supervisor's per-minute decision (SPEC §3.2). Pure -- no IO.

This is the core unit-test target. The monitor has no memory: it reads the
current snapshot and the current time and decides what to do for one task this
minute. Deduplication relies on the task's ``latest_progress_time``, never on
remembered history.

Decision table (for a study/work task in the current logical day that is NOT the
day's last task -- the last task is never nagged, only a boundary):

    status        time situation                                  -> action
    COMPLETED     --                                              -> SKIP
    NOT_STARTED   before planned start                            -> WAIT
    NOT_STARTED   at/after planned start                          -> NAG_START
    OVERDUE       before planned end, on a backoff nag minute     -> NAG_START
    OVERDUE       before planned end, off a nag minute            -> WAIT
    OVERDUE       after planned end                               -> STOP_NAGGING
    IN_PROGRESS   before midpoint                                 -> WAIT
    IN_PROGRESS   past midpoint (but not end), progress < midpoint -> MIDPOINT_CHECK
    IN_PROGRESS   past end, progress < end                        -> END_CHECK_HANDOFF
    IN_PROGRESS   already asked (progress timestamp fresh enough) -> WAIT

End takes priority over midpoint: the two IN_PROGRESS rows are mutually
exclusive via "but not end", so a restart that skipped the whole midpoint window
goes straight to the end handoff (SPEC §3.2, A1).
"""

from __future__ import annotations

import enum
from datetime import datetime

from .models import Task


class Action(enum.Enum):
    """What the supervisor should do with one task this minute."""

    SKIP = "skip"
    WAIT = "wait"
    NAG_START = "nag_start"
    STOP_NAGGING = "stop_nagging"
    MIDPOINT_CHECK = "midpoint_check"
    END_CHECK_HANDOFF = "end_check_handoff"


def decide(
    task: Task,
    now: datetime,
    *,
    planned_start: datetime,
    planned_end: datetime,
    midpoint: datetime,
    is_last_task: bool,
) -> Action:
    """Decide the action for ``task`` at ``now`` (see module docstring)."""
    raise NotImplementedError
