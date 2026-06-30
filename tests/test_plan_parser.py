"""Tests for the plan set-diff sync (SPEC §3.1)."""

from __future__ import annotations

from procrastination_terminator.models import Status, Task, TaskType
from procrastination_terminator.plan_parser import diff_sync, find_duplicate_codes


def task(code: str, date: str, *, status: Status = Status.NOT_STARTED) -> Task:
    return Task(
        code=code,
        date=date,
        planned_start="14:00",
        planned_end="18:00",
        description="some task",
        type=TaskType.STUDY,
        status=status,
    )


def test_add_missing_delete_extra_keep_matched() -> None:
    existing = [task("0313-1400-PGM", "03.13"), task("0313-1800-RUN", "03.13")]
    parsed = [task("0313-1400-PGM", "03.13"), task("0313-2000-EAT", "03.13")]

    plan = diff_sync(existing, parsed, "03.13")

    assert [t.code for t in plan.to_add] == ["0313-2000-EAT"]
    assert plan.to_delete == ["0313-1800-RUN"]
    assert [t.code for t in plan.kept] == ["0313-1400-PGM"]


def test_matched_row_keeps_existing_state_not_parsed() -> None:
    # The kept row must carry the existing runtime state, not the freshly parsed one.
    existing = [task("0313-1400-PGM", "03.13", status=Status.IN_PROGRESS)]
    parsed = [task("0313-1400-PGM", "03.13", status=Status.NOT_STARTED)]

    plan = diff_sync(existing, parsed, "03.13")

    assert plan.kept[0].status is Status.IN_PROGRESS
    assert plan.to_add == []
    assert plan.to_delete == []


def test_pre_today_rows_are_out_of_scope() -> None:
    existing = [task("0312-1400-PGM", "03.12"), task("0313-1400-PGM", "03.13")]
    parsed = [task("0314-0900-GYM", "03.14")]  # only a future task in the plan

    plan = diff_sync(existing, parsed, "03.13")

    # Yesterday's row is neither deleted nor reported; only today's gets deleted.
    assert plan.to_delete == ["0313-1400-PGM"]
    assert [t.code for t in plan.to_add] == ["0314-0900-GYM"]
    assert plan.kept == []


def test_past_tasks_in_plan_are_ignored() -> None:
    plan = diff_sync([], [task("0312-1400-PGM", "03.12")], "03.13")
    assert plan.to_add == []


def test_find_duplicate_codes() -> None:
    tasks = [
        task("0313-1400-PGM", "03.13"),
        task("0313-1400-PGM", "03.13"),
        task("0313-1800-RUN", "03.13"),
    ]
    assert find_duplicate_codes(tasks) == ["0313-1400-PGM"]


def test_find_duplicate_codes_none() -> None:
    tasks = [task("0313-1400-PGM", "03.13"), task("0313-1800-RUN", "03.13")]
    assert find_duplicate_codes(tasks) == []
