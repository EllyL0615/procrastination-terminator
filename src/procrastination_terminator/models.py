"""Core data model: one task = one row of progress.csv (SPEC §2)."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class TaskType(enum.Enum):
    """Task type; judged by the LLM at insert time, editable by hand (SPEC §2)."""

    STUDY = "study"
    WORK = "work"
    OUTING = "outing"
    OTHER = "other"


class Status(enum.Enum):
    """Lifecycle state of a study/work task (SPEC §4)."""

    NOT_STARTED = "not_started"
    OVERDUE = "overdue"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


# progress.csv column order (SPEC §2). history.csv shares the same schema.
CSV_COLUMNS: tuple[str, ...] = (
    "code",
    "date",
    "planned_time",
    "task",
    "type",
    "status",
    "actual_time",
    "latest_progress",
    "latest_progress_time",
)


@dataclass
class Task:
    """A single task row.

    `planned_start` / `planned_end` are raw ``HH:MM`` clock strings; `planned_end`
    is the *next* task's start time (SPEC §2). Absolute, timezone-aware datetimes
    are derived on demand via :mod:`procrastination_terminator.daytime`.

    `latest_progress` is free text the user may edit; `latest_progress_time` is the
    machine-owned timestamp the monitor uses for deduplication (SPEC §2, A5).
    """

    code: str
    date: str
    planned_start: str
    planned_end: str
    description: str
    type: TaskType
    status: Status
    actual_start: str | None = None
    actual_end: str | None = None
    latest_progress: str = ""
    latest_progress_time: str | None = None
