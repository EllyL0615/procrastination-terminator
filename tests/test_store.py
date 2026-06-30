"""Tests for CSV persistence (SPEC §2, §3.1)."""

from __future__ import annotations

from pathlib import Path

from procrastination_terminator import store
from procrastination_terminator.models import Status, Task, TaskType


def task(
    code: str,
    date: str,
    *,
    status: Status = Status.NOT_STARTED,
    actual_start: str | None = None,
    actual_end: str | None = None,
    latest_progress: str = "",
    latest_progress_time: str | None = None,
) -> Task:
    return Task(
        code=code,
        date=date,
        planned_start="14:00",
        planned_end="18:00",
        description="some task",
        type=TaskType.STUDY,
        status=status,
        actual_start=actual_start,
        actual_end=actual_end,
        latest_progress=latest_progress,
        latest_progress_time=latest_progress_time,
    )


def test_load_missing_file_is_empty(tmp_path: Path) -> None:
    assert store.load(str(tmp_path / "nope.csv")) == []


def test_round_trip(tmp_path: Path) -> None:
    path = str(tmp_path / "progress.csv")
    done = task(
        "0313-1400-PGM",
        "03.13",
        status=Status.COMPLETED,
        actual_start="14:08",
        actual_end="17:55",
        latest_progress="finished the exercises",
        latest_progress_time="2026-03-13T17:55:00+00:00",
    )
    in_progress = task("0313-1800-RUN", "03.13", status=Status.IN_PROGRESS, actual_start="18:02")
    store.upsert_changed(path, [done, in_progress])
    assert store.load(path) == [done, in_progress]


def test_upsert_updates_existing_and_appends_new(tmp_path: Path) -> None:
    path = str(tmp_path / "progress.csv")
    a = task("0313-1400-PGM", "03.13")
    b = task("0313-1800-RUN", "03.13")
    store.upsert_changed(path, [a, b])

    a_started = task("0313-1400-PGM", "03.13", status=Status.IN_PROGRESS, actual_start="14:05")
    c = task("0313-2000-EAT", "03.13", status=Status.NOT_STARTED)
    store.upsert_changed(path, [a_started, c])

    loaded = store.load(path)
    assert loaded == [a_started, b, c]  # a replaced in place, b untouched, c appended


def test_upsert_preserves_unrelated_rows(tmp_path: Path) -> None:
    # A row the supervisor does not touch this tick must survive verbatim (A6).
    path = str(tmp_path / "progress.csv")
    a = task("0313-1400-PGM", "03.13")
    b = task("0313-1800-RUN", "03.13", latest_progress="hand-written note", status=Status.OVERDUE)
    store.upsert_changed(path, [a, b])

    store.upsert_changed(path, [task("0313-1400-PGM", "03.13", status=Status.COMPLETED)])

    loaded = {t.code: t for t in store.load(path)}
    assert loaded["0313-1800-RUN"] == b


def test_archive_past_moves_old_rows(tmp_path: Path) -> None:
    progress = str(tmp_path / "progress.csv")
    history = str(tmp_path / "history.csv")
    yesterday = task("0312-1400-PGM", "03.12", status=Status.COMPLETED)
    today = task("0313-1400-PGM", "03.13")
    tomorrow = task("0314-1400-PGM", "03.14")
    store.upsert_changed(progress, [yesterday, today, tomorrow])

    store.archive_past(progress, history, "03.13")

    assert store.load(progress) == [today, tomorrow]
    assert store.load(history) == [yesterday]


def test_archive_past_appends_to_existing_history(tmp_path: Path) -> None:
    progress = str(tmp_path / "progress.csv")
    history = str(tmp_path / "history.csv")
    older = task("0311-1400-PGM", "03.11", status=Status.COMPLETED)
    store.upsert_changed(history, [older])
    store.upsert_changed(progress, [task("0312-1400-PGM", "03.12"), task("0313-1400-PGM", "03.13")])

    store.archive_past(progress, history, "03.13")

    assert [t.code for t in store.load(history)] == ["0311-1400-PGM", "0312-1400-PGM"]
    assert [t.code for t in store.load(progress)] == ["0313-1400-PGM"]


def test_archive_past_noop_when_nothing_old(tmp_path: Path) -> None:
    progress = str(tmp_path / "progress.csv")
    history = str(tmp_path / "history.csv")
    store.upsert_changed(progress, [task("0313-1400-PGM", "03.13")])

    store.archive_past(progress, history, "03.13")

    assert [t.code for t in store.load(progress)] == ["0313-1400-PGM"]
    assert store.load(history) == []
