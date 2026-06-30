"""Read/write progress.csv and history.csv with stdlib ``csv`` (SPEC §2, §3.1).

The file is the single source of truth. To avoid clobbering concurrent external
edits, the supervisor re-reads the file and rewrites only the rows it actually
changes this tick, never a wholesale overwrite from a stale snapshot (SPEC §3.2,
A6). Writes go through a temp file + atomic ``os.replace`` so a crash never
leaves a half-written file.
"""

from __future__ import annotations

import contextlib
import csv
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .models import CSV_COLUMNS, Status, Task, TaskType


def _join_range(start: str | None, end: str | None) -> str:
    """Render a head/tail pair as ``"start-end"`` / ``"start-"`` / ``""``."""
    if not start:
        return ""
    return f"{start}-{end}" if end else f"{start}-"


def _split_range(value: str) -> tuple[str | None, str | None]:
    """Inverse of :func:`_join_range`; splits on the first ``-``."""
    if not value:
        return None, None
    head, _, tail = value.partition("-")
    return (head or None), (tail or None)


def _to_row(task: Task) -> dict[str, str]:
    return {
        "code": task.code,
        "date": task.date,
        "planned_time": f"{task.planned_start}-{task.planned_end}",
        "task": task.description,
        "type": task.type.value,
        "status": task.status.value,
        "actual_time": _join_range(task.actual_start, task.actual_end),
        "latest_progress": task.latest_progress,
        "latest_progress_time": task.latest_progress_time or "",
    }


def _from_row(row: dict[str, str]) -> Task:
    planned_start, planned_end = _split_range(row["planned_time"])
    actual_start, actual_end = _split_range(row["actual_time"])
    return Task(
        code=row["code"],
        date=row["date"],
        planned_start=planned_start or "",
        planned_end=planned_end or "",
        description=row["task"],
        type=TaskType(row["type"]),
        status=Status(row["status"]),
        actual_start=actual_start,
        actual_end=actual_end,
        latest_progress=row["latest_progress"],
        latest_progress_time=row["latest_progress_time"] or None,
    )


def _read_raw(file: Path) -> list[dict[str, str]]:
    """Read the CSV into raw column->value dicts (empty list if absent)."""
    if not file.exists():
        return []
    with file.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header = rows[0]
    out: list[dict[str, str]] = []
    for record in rows[1:]:
        if not record:
            continue
        padded = record + [""] * (len(header) - len(record))
        out.append(dict(zip(header, padded, strict=False)))
    return out


def _write_atomic(file: Path, rows: list[dict[str, str]]) -> None:
    """Write header + rows to ``file`` atomically (temp file + replace)."""
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=file.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(list(CSV_COLUMNS))
            for row in rows:
                writer.writerow([row.get(col, "") for col in CSV_COLUMNS])
        os.replace(tmp, file)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def load(path: str) -> list[Task]:
    """Load all task rows from a CSV file (empty list if the file is absent)."""
    return [_from_row(row) for row in _read_raw(Path(path))]


def write_all(path: str, tasks: list[Task]) -> None:
    """Replace the whole file with ``tasks`` (used by sync, which deletes rows)."""
    _write_atomic(Path(path), [_to_row(t) for t in tasks])


def upsert_changed(path: str, changed: Iterable[Task]) -> None:
    """Re-read ``path`` and write back only the given changed rows (A6).

    Rows not in ``changed`` are written back verbatim from the fresh read, so a
    concurrent manual edit to some other row is preserved. Matching is by
    ``code``: an existing code is replaced in place, a new one is appended.
    """
    updates = list(changed)
    if not updates:
        return
    file = Path(path)
    rows = _read_raw(file)
    index = {row["code"]: i for i, row in enumerate(rows)}
    for task in updates:
        row = _to_row(task)
        pos = index.get(task.code)
        if pos is None:
            index[task.code] = len(rows)
            rows.append(row)
        else:
            rows[pos] = row
    _write_atomic(file, rows)


def archive_past(progress_path: str, history_path: str, current_logical_day: str) -> None:
    """Move rows older than the current logical day into history.csv (SPEC §3.1, B3).

    ``current_logical_day`` is a ``date`` column value (e.g. ``"03.13"``); rows
    whose ``date`` sorts before it are archived. Comparison is lexical, which
    assumes the retained window stays within one year (``MM.DD`` carries no year).
    History is appended first, then progress is trimmed, so a crash never drops a
    row (at worst it is archived twice).
    """
    progress = Path(progress_path)
    rows = _read_raw(progress)
    past = [r for r in rows if r["date"] < current_logical_day]
    if not past:
        return
    kept = [r for r in rows if r["date"] >= current_logical_day]
    history = Path(history_path)
    _write_atomic(history, _read_raw(history) + past)
    _write_atomic(progress, kept)
