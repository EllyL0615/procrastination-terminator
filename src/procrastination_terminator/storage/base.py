"""The storage backend interface (SPEC §3, §9).

The supervisor is memoryless: it re-reads a full snapshot from the *single source
of truth* every tick and writes back only the rows it changed. That source was a
local file; this Protocol lets it be a Notion database instead, without touching
the pure decision logic. ``day_start`` and the concrete targets (file paths or
Notion ids) are configuration the backend holds, so the methods carry only domain
data. All IO methods are async so a network-backed implementation can await; the
file backend simply wraps the synchronous stdlib-csv store.

``current_context`` is intentionally synchronous: it returns the user's standing
context (glossary/tone) that every LLM prompt folds in, so it must be cheap. A
network backend caches it and refreshes on demand via ``refresh_context`` (bot
startup / day-start / an explicit reload command); the file backend just reads
the file each call.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from ..models import Task


@runtime_checkable
class StorageBackend(Protocol):
    async def load_progress(self) -> list[Task]:
        """Return all progress rows (today-and-future), empty if none."""
        ...

    async def upsert_changed(self, changed: Iterable[Task]) -> None:
        """Write back only ``changed`` rows, matched by ``code``; never clobber others."""
        ...

    async def write_all(self, tasks: list[Task]) -> None:
        """Replace the whole progress set with ``tasks`` (used by sync/modify deletes)."""
        ...

    async def archive_past(self, current_logical_day: str) -> None:
        """Move rows dated before ``current_logical_day`` out of the working set."""
        ...

    async def read_plan(self) -> str:
        """Return the raw free-form plan text ('' if none)."""
        ...

    async def refresh_context(self) -> None:
        """Refresh the cached standing context (no-op for backends that read live)."""
        ...

    def current_context(self) -> str:
        """Return the current standing context text ('' if none); must be cheap."""
        ...

    async def aclose(self) -> None:
        """Release any resources (HTTP clients, etc.)."""
        ...
