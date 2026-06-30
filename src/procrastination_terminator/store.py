"""Read/write progress.csv and history.csv with stdlib ``csv`` (SPEC §2, §3.1).

The file is the single source of truth. To avoid clobbering concurrent external
edits, the supervisor re-reads the file and rewrites only the rows it actually
changes this tick, never a wholesale overwrite (SPEC §3.2, A6).
"""

from __future__ import annotations

from collections.abc import Iterable

from .models import Task


def load(path: str) -> list[Task]:
    """Load all task rows from a CSV file (empty list if the file is absent)."""
    raise NotImplementedError


def upsert_changed(path: str, changed: Iterable[Task]) -> None:
    """Re-read ``path`` and write back only the given changed rows (A6)."""
    raise NotImplementedError


def archive_past(progress_path: str, history_path: str, current_logical_day: str) -> None:
    """Move rows older than the current logical day into history.csv (SPEC §3.1, B3)."""
    raise NotImplementedError
