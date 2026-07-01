"""Storage backends (SPEC §3, §9): select the single source of truth by config.

``build_backend`` picks the implementation from ``config.storage_backend``; only
the local-file backend exists today, with a Notion backend added next.
"""

from __future__ import annotations

from ..config import Config
from .base import StorageBackend
from .file_backend import FileBackend

__all__ = ["FileBackend", "StorageBackend", "build_backend"]


def build_backend(config: Config) -> StorageBackend:
    """Construct the configured storage backend (file only, for now)."""
    return FileBackend(config)
