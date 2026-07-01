"""Local-file storage backend: a thin async wrapper over :mod:`..store` (SPEC §3).

The store module (stdlib ``csv``, atomic writes, re-read-before-write) stays the
single source of truth for file semantics and keeps its own unit tests; this only
adapts it to the async :class:`StorageBackend` interface and folds in the two
read-only files the bot also touches (plan.txt, context.txt). Nothing here blocks
meaningfully -- local reads/writes are sub-millisecond against a 60s tick -- so the
sync store functions are called directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .. import store
from ..config import Config
from ..models import Task


class FileBackend:
    """Delegates every operation to the synchronous :mod:`..store` functions."""

    def __init__(self, config: Config) -> None:
        self._progress_path = config.progress_path
        self._history_path = config.history_path
        self._plan_path = config.plan_path
        self._context_path = config.context_path

    async def load_progress(self) -> list[Task]:
        return store.load(self._progress_path)

    async def upsert_changed(self, changed: Iterable[Task]) -> None:
        store.upsert_changed(self._progress_path, changed)

    async def write_all(self, tasks: list[Task]) -> None:
        store.write_all(self._progress_path, tasks)

    async def archive_past(self, current_logical_day: str) -> None:
        store.archive_past(self._progress_path, self._history_path, current_logical_day)

    async def read_plan(self) -> str:
        path = Path(self._plan_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    async def refresh_context(self) -> None:
        return None  # read live in current_context; nothing to cache

    def current_context(self) -> str:
        try:
            return Path(self._context_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    async def aclose(self) -> None:
        return None
