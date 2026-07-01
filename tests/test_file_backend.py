"""FileBackend must delegate to store.py without changing any semantics (SPEC §3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from procrastination_terminator import store
from procrastination_terminator.config import Config
from procrastination_terminator.models import Status, Task, TaskType
from procrastination_terminator.storage.file_backend import FileBackend


def _config(tmp_path: Path) -> Config:
    return Config(
        discord_token="t",
        discord_user_id=1,
        discord_channel_id=2,
        llm_api_key="k",
        llm_base_url="http://localhost",
        llm_model="m",
        plan_path=str(tmp_path / "plan.txt"),
        progress_path=str(tmp_path / "progress.csv"),
        history_path=str(tmp_path / "history.csv"),
        context_path=str(tmp_path / "context.txt"),
    )


def _task(code: str = "0701-1400-GAME", date: str = "07.01") -> Task:
    return Task(
        code=code,
        date=date,
        planned_start="14:00",
        planned_end="15:00",
        description="Game Chap1",
        type=TaskType.STUDY,
        status=Status.NOT_STARTED,
        notes="30min problems",
    )


def test_load_empty_returns_empty(tmp_path: Path) -> None:
    backend = FileBackend(_config(tmp_path))
    assert asyncio.run(backend.load_progress()) == []


def test_upsert_then_load_roundtrip(tmp_path: Path) -> None:
    backend = FileBackend(_config(tmp_path))
    asyncio.run(backend.upsert_changed([_task()]))
    loaded = asyncio.run(backend.load_progress())
    assert len(loaded) == 1
    assert loaded[0].code == "0701-1400-GAME"
    assert loaded[0].notes == "30min problems"
    assert loaded[0].status is Status.NOT_STARTED


def test_upsert_preserves_unrelated_rows(tmp_path: Path) -> None:
    backend = FileBackend(_config(tmp_path))
    asyncio.run(backend.upsert_changed([_task("0701-1400-GAME"), _task("0701-1500-MATH")]))
    changed = _task("0701-1400-GAME")
    changed.status = Status.COMPLETED
    asyncio.run(backend.upsert_changed([changed]))
    loaded = {t.code: t for t in asyncio.run(backend.load_progress())}
    assert loaded["0701-1400-GAME"].status is Status.COMPLETED
    assert loaded["0701-1500-MATH"].status is Status.NOT_STARTED


def test_read_plan_missing_is_empty(tmp_path: Path) -> None:
    backend = FileBackend(_config(tmp_path))
    assert asyncio.run(backend.read_plan()) == ""


def test_read_plan_returns_text(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Path(cfg.plan_path).write_text("07.01\n14:00 Game", encoding="utf-8")
    assert asyncio.run(FileBackend(cfg).read_plan()) == "07.01\n14:00 Game"


def test_current_context_missing_is_empty(tmp_path: Path) -> None:
    assert FileBackend(_config(tmp_path)).current_context() == ""


def test_current_context_reads_file(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    Path(cfg.context_path).write_text("Game = 博弈论", encoding="utf-8")
    assert FileBackend(cfg).current_context() == "Game = 博弈论"


def test_archive_past_moves_old_rows_to_history(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    backend = FileBackend(cfg)
    asyncio.run(backend.upsert_changed([_task("0630-1400-OLD", "06.30"), _task()]))
    asyncio.run(backend.archive_past("07.01"))
    remaining = asyncio.run(backend.load_progress())
    assert [t.code for t in remaining] == ["0701-1400-GAME"]
    assert [t.code for t in store.load(cfg.history_path)] == ["0630-1400-OLD"]
