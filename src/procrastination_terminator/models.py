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
    """Lifecycle state of a study/work task (SPEC §4).

    The values are the exact keywords written to progress.csv and shown by
    ``!progress`` -- one shared vocabulary (``todo`` / ``overdue`` / ``started`` /
    ``completed``). The member names describe the same states in code, so
    ``NOT_STARTED`` serialises as ``todo`` and ``IN_PROGRESS`` as ``started``.
    """

    NOT_STARTED = "todo"
    OVERDUE = "overdue"
    IN_PROGRESS = "started"
    COMPLETED = "completed"


class Personality(enum.Enum):
    """Message personality flavour (SPEC §4.5)."""

    GENTLE = "gentle"
    STRICT = "strict"
    SARCASTIC = "sarcastic"


# progress.csv column order (SPEC §2). history.csv shares the same schema.
CSV_COLUMNS: tuple[str, ...] = (
    "code",
    "date",
    "planned_time",
    "task",
    "notes",
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

    `notes` is task-specific guidance parsed from plan.txt (the lines written under a
    task); plan.txt owns it, so sync refreshes it even on matched rows (SPEC §3.1).
    """

    code: str
    date: str
    planned_start: str
    planned_end: str
    description: str
    type: TaskType
    status: Status
    notes: str = ""
    actual_start: str | None = None
    actual_end: str | None = None
    latest_progress: str = ""
    latest_progress_time: str | None = None
