"""Tests for the supervisor decision table (SPEC §3.2)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from procrastination_terminator.models import Status, Task, TaskType
from procrastination_terminator.monitor import Action, decide

TZ = ZoneInfo("Europe/London")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 3, 13, hour, minute, tzinfo=TZ)


# Planned window 14:00-18:00, midpoint 16:00.
START = at(14)
END = at(18)
MID = at(16)


def make(status: Status, *, progress: datetime | None = None) -> Task:
    return Task(
        code="0313-1400-PGM",
        date="03.13",
        planned_start="14:00",
        planned_end="18:00",
        description="prog",
        type=TaskType.STUDY,
        status=status,
        latest_progress_time=progress.isoformat() if progress is not None else None,
    )


def call(task: Task, now: datetime, *, last: bool = False) -> Action:
    return decide(task, now, planned_start=START, planned_end=END, midpoint=MID, is_last_task=last)


def test_completed_is_skipped() -> None:
    assert call(make(Status.COMPLETED), at(16)) is Action.SKIP


def test_last_task_is_never_nagged() -> None:
    # Regardless of status, the day's last task is only a boundary.
    assert call(make(Status.NOT_STARTED), at(15), last=True) is Action.SKIP
    assert call(make(Status.OVERDUE), at(15), last=True) is Action.SKIP


def test_not_started_before_start_waits() -> None:
    assert call(make(Status.NOT_STARTED), at(13, 59)) is Action.WAIT


def test_not_started_at_or_after_start_nags() -> None:
    assert call(make(Status.NOT_STARTED), at(14)) is Action.NAG_START
    assert call(make(Status.NOT_STARTED), at(15)) is Action.NAG_START  # late first contact


def test_not_started_past_end_stops_without_nagging() -> None:
    # The whole window is gone (e.g. the bot was down all afternoon): no pointless
    # "start now" nag -- go straight to overdue (caller flips it) for the summary.
    assert call(make(Status.NOT_STARTED), at(18)) is Action.STOP_NAGGING
    assert call(make(Status.NOT_STARTED), at(19)) is Action.STOP_NAGGING


def test_overdue_nags_only_on_backoff_minutes() -> None:
    assert call(make(Status.OVERDUE), at(14, 8)) is Action.NAG_START  # minute 8 is on-curve
    assert call(make(Status.OVERDUE), at(14, 9)) is Action.WAIT  # minute 9 is off-curve


def test_overdue_past_end_stops_nagging() -> None:
    assert call(make(Status.OVERDUE), at(18)) is Action.STOP_NAGGING
    assert call(make(Status.OVERDUE), at(19)) is Action.STOP_NAGGING


def test_in_progress_before_midpoint_waits() -> None:
    task = make(Status.IN_PROGRESS, progress=at(14, 5))
    assert call(task, at(15, 59)) is Action.WAIT


def test_in_progress_past_midpoint_unasked_checks() -> None:
    task = make(Status.IN_PROGRESS, progress=at(14, 5))
    assert call(task, at(16, 1)) is Action.MIDPOINT_CHECK


def test_in_progress_past_midpoint_already_asked_waits() -> None:
    task = make(Status.IN_PROGRESS, progress=at(16, 1))
    assert call(task, at(16, 30)) is Action.WAIT


def test_in_progress_past_end_unasked_hands_off() -> None:
    task = make(Status.IN_PROGRESS, progress=at(16, 1))
    assert call(task, at(18, 1)) is Action.END_CHECK_HANDOFF


def test_in_progress_past_end_already_asked_waits() -> None:
    task = make(Status.IN_PROGRESS, progress=at(18, 1))
    assert call(task, at(18, 30)) is Action.WAIT


def test_end_takes_priority_over_midpoint_after_restart() -> None:
    # Down through the whole midpoint window: progress still pre-midpoint, now past end.
    task = make(Status.IN_PROGRESS, progress=at(14, 0))
    assert call(task, at(18, 1)) is Action.END_CHECK_HANDOFF


def test_in_progress_missing_progress_time_triggers_check() -> None:
    task = make(Status.IN_PROGRESS, progress=None)
    assert call(task, at(16, 1)) is Action.MIDPOINT_CHECK
