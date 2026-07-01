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
    NOT_STARTED   at/after start, before planned end              -> NAG_START
    NOT_STARTED   after planned end (window fully missed)         -> STOP_NAGGING
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

from . import backoff
from .models import Status, Task


class Action(enum.Enum):
    """What the supervisor should do with one task this minute."""

    SKIP = "skip"
    WAIT = "wait"
    NAG_START = "nag_start"
    STOP_NAGGING = "stop_nagging"
    MIDPOINT_CHECK = "midpoint_check"
    END_CHECK_HANDOFF = "end_check_handoff"


def _progress_time(task: Task) -> datetime | None:
    """The timestamp the monitor dedupes against, or None if never recorded."""
    if task.latest_progress_time is None:
        return None
    return datetime.fromisoformat(task.latest_progress_time)


def _before(moment: datetime | None, boundary: datetime) -> bool:
    """Whether ``moment`` is before ``boundary``; a missing moment counts as before."""
    return moment is None or moment < boundary


def decide(
    task: Task,
    now: datetime,
    *,
    planned_start: datetime,
    planned_end: datetime,
    midpoint: datetime,
    is_last_task: bool,
) -> Action:
    """Decide the action for ``task`` at ``now`` (see module docstring).

    Called for a ``study``/``work`` task in the current logical day. The planned
    boundaries are resolved by the caller (via :mod:`daytime`); the dedup
    timestamp is read from the task itself.
    """
    if task.status is Status.COMPLETED:
        return Action.SKIP
    if is_last_task:
        # The day's last task is never nagged, only a time boundary (SPEC §4.2, §7).
        return Action.SKIP

    if task.status is Status.NOT_STARTED:
        if now < planned_start:
            return Action.WAIT
        if now >= planned_end:
            # The whole window is already gone: nagging "start now" is pointless, so
            # go straight to OVERDUE without a nag (caller flips it), left for the
            # day-end summary -- symmetric with an OVERDUE task past its end.
            return Action.STOP_NAGGING
        return Action.NAG_START  # first nag; caller flips status to OVERDUE

    if task.status is Status.OVERDUE:
        if now >= planned_end:
            return Action.STOP_NAGGING  # give up nagging; keep status OVERDUE
        if backoff.should_nag(now - planned_start):
            return Action.NAG_START
        return Action.WAIT

    if task.status is Status.IN_PROGRESS:
        progressed_at = _progress_time(task)
        # End is checked before midpoint so a restart that skipped the midpoint
        # window goes straight to the handoff (SPEC §3.2, A1).
        if now >= planned_end:
            return Action.END_CHECK_HANDOFF if _before(progressed_at, planned_end) else Action.WAIT
        if now >= midpoint:
            return Action.MIDPOINT_CHECK if _before(progressed_at, midpoint) else Action.WAIT
        return Action.WAIT

    return Action.WAIT  # unreachable: all Status members handled above
