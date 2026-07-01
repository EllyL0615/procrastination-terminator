"""Tests for the plan set-diff sync (SPEC §3.1)."""

from __future__ import annotations

import pytest

from procrastination_terminator.models import Status, Task, TaskType
from procrastination_terminator.plan_parser import (
    DuplicateCodeError,
    build_tasks,
    diff_sync,
    find_duplicate_codes,
    parse_plan_text,
)


def entry(date: str, time: str, subject: str, *, type: str = "study") -> dict[str, str]:
    return {"date": date, "time": time, "subject": subject, "description": "x", "type": type}


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


def test_build_tasks_chains_planned_end_within_day() -> None:
    tasks = build_tasks(
        [entry("03.13", "18:00", "RUN"), entry("03.13", "14:00", "PGM")]  # out of order
    )
    assert [t.code for t in tasks] == ["0313-1400-PGM", "0313-1800-RUN"]
    assert tasks[0].planned_start == "14:00"
    assert tasks[0].planned_end == "18:00"  # next same-day task's start


def test_build_tasks_last_task_ends_at_own_start() -> None:
    tasks = build_tasks([entry("03.13", "23:00", "SLEEP")])
    assert tasks[0].planned_end == "23:00"


def test_build_tasks_does_not_chain_across_days() -> None:
    tasks = build_tasks([entry("03.13", "22:00", "READ"), entry("03.14", "09:00", "GYM")])
    assert tasks[0].planned_end == "22:00"  # last of its day, no next same-day task


def test_build_tasks_after_midnight_task_sorts_to_end_of_logical_day() -> None:
    # 00:00 sleep is the *after-midnight* tail of 03.13's logical day (SPEC §5), so it
    # must sort last -- not first -- and it is the day's boundary task (start == end).
    tasks = build_tasks(
        [
            entry("03.13", "10:00", "PGM"),
            entry("03.13", "00:00", "SLEEP"),  # midnight, logically the day's last
        ]
    )
    assert [t.code for t in tasks] == ["0313-1000-PGM", "0313-0000-SLEEP"]
    assert tasks[0].planned_end == "00:00"  # PGM runs until sleep begins, not 10:00-10:00
    assert tasks[1].planned_end == "00:00"  # sleep is the boundary: start == end


def test_build_tasks_full_day_with_midnight_boundary() -> None:
    # The reported bug: a plan whose last written line is 00:00 sleep.
    tasks = build_tasks(
        [
            entry("07.01", "05:30", "LOGIC"),
            entry("07.01", "07:00", "QUANTUM"),
            entry("07.01", "10:00", "REVISE"),
            entry("07.01", "00:00", "SLEEP"),
        ]
    )
    assert [(t.planned_start, t.planned_end) for t in tasks] == [
        ("05:30", "07:00"),
        ("07:00", "10:00"),
        ("10:00", "00:00"),
        ("00:00", "00:00"),
    ]


def test_build_tasks_rejects_duplicate_code() -> None:
    with pytest.raises(DuplicateCodeError):
        build_tasks([entry("03.13", "14:00", "PGM"), entry("03.13", "14:00", "PGM")])


def test_build_tasks_carries_notes() -> None:
    tasks = build_tasks([{**entry("03.13", "14:00", "PGM"), "notes": "read chapter 1"}])
    assert tasks[0].notes == "read chapter 1"


# -- deterministic backbone parse (SPEC §2) ----------------------------------


def test_parse_plan_text_extracts_tasks_under_date_header() -> None:
    entries = parse_plan_text("07.01 周三 Game\n14:00 Game Chap1\n15:00 Game Chap2\n")
    assert [(e["date"], e["time"], e["subject"], e["description"]) for e in entries] == [
        ("07.01", "14:00", "GAME", "Game Chap1"),
        ("07.01", "15:00", "GAME", "Game Chap2"),
    ]


def test_parse_plan_text_date_header_trailing_text_ignored() -> None:
    # "07.01 Game" -> only the date is taken; the trailing "Game" is a note to self.
    entries = parse_plan_text("07.01 Game\n14:00 Study\n")
    assert len(entries) == 1
    assert entries[0]["date"] == "07.01"


def test_parse_plan_text_non_task_lines_are_skipped() -> None:
    # Indented notes with no leading time are not tasks (the LLM attaches them later).
    plan = "07.01\n14:00 Game Chap1\n    30min 刷题\n    导图\n15:00 Game Chap2\n"
    assert [e["time"] for e in parse_plan_text(plan)] == ["14:00", "15:00"]


def test_parse_plan_text_task_before_any_date_header_dropped() -> None:
    assert parse_plan_text("14:00 orphan task\n") == []


def test_parse_plan_text_normalizes_time_and_derives_cjk_subject() -> None:
    entries = parse_plan_text("7.1\n6:11 睡觉\n")
    assert (entries[0]["date"], entries[0]["time"], entries[0]["subject"]) == (
        "07.01",
        "06:11",
        "睡觉",
    )
