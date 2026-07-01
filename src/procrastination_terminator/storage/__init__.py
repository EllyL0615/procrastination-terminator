"""Storage backends (SPEC §3, §9): select the single source of truth by config.

``build_backend`` picks the implementation from ``config.storage_backend``; only
the local-file backend exists today, with a Notion backend added next.
"""

from __future__ import annotations

from ..config import Config
from .base import StorageBackend
from .file_backend import FileBackend
from .notion_backend import NotionBackend

__all__ = ["FileBackend", "NotionBackend", "StorageBackend", "build_backend"]


def build_backend(config: Config) -> StorageBackend:
    """Construct the storage backend named by ``config.storage_backend`` (SPEC §9)."""
    if config.storage_backend == "file":
        return FileBackend(config)
    if config.storage_backend == "notion":
        return NotionBackend(config)
    raise ValueError(f"unknown STORAGE_BACKEND: {config.storage_backend!r}")
