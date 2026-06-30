"""Tests for logical-day helpers (SPEC §5, §3.2)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from procrastination_terminator.daytime import logical_day_of, midpoint, resolve

TZ = ZoneInfo("Europe/London")
DAY_START = time(4, 0)


def test_evening_clock_stays_on_same_calendar_day() -> None:
    assert resolve(date(2026, 3, 13), time(23, 0), DAY_START, TZ) == datetime(
        2026, 3, 13, 23, 0, tzinfo=TZ
    )


def test_after_midnight_clock_rolls_to_next_calendar_day() -> None:
    assert resolve(date(2026, 3, 13), time(1, 0), DAY_START, TZ) == datetime(
        2026, 3, 14, 1, 0, tzinfo=TZ
    )


def test_cross_midnight_midpoint() -> None:
    start = resolve(date(2026, 3, 13), time(23, 0), DAY_START, TZ)
    end = resolve(date(2026, 3, 13), time(1, 0), DAY_START, TZ)
    assert midpoint(start, end) == datetime(2026, 3, 14, 0, 0, tzinfo=TZ)


def test_logical_day_before_day_start_is_previous_date() -> None:
    moment = datetime(2026, 3, 14, 1, 0, tzinfo=TZ)
    assert logical_day_of(moment, DAY_START) == date(2026, 3, 13)


def test_logical_day_after_day_start_is_same_date() -> None:
    moment = datetime(2026, 3, 13, 23, 0, tzinfo=TZ)
    assert logical_day_of(moment, DAY_START) == date(2026, 3, 13)
