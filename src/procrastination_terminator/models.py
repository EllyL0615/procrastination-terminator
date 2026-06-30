"""Core data model: one task = one row of progress.csv (SPEC §2)."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class TaskType(enum.Enum):
    """Task type; judged by the LLM at insert time, editable by hand (SPEC §2)."""

    STUDY = "学习"
    WORK = "工作"
    OUTING = "外出"
    OTHER = "其他"


class Status(enum.Enum):
    """Lifecycle state of a study/work task (SPEC §4)."""

    NOT_STARTED = "未开始"
    PROMPTING = "催促中"
    IN_PROGRESS = "进行中"
    DONE = "已完成"


# progress.csv column order (SPEC §2). history.csv shares the same schema.
CSV_COLUMNS: tuple[str, ...] = (
    "代号",
    "日期",
    "计划时间",
    "任务",
    "类型",
    "状态",
    "实际时间",
    "最新进度",
    "最新进度时间",
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
