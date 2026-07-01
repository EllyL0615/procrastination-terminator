"""Tests for logical-day helpers (SPEC §5, §3.2)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from procrastination_terminator.daytime import (
    date_from_md,
    logical_day_of,
    logical_order,
    midpoint,
    parse_clock,
    resolve,
)

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


def test_parse_clock_lenient_about_leading_zero() -> None:
    assert parse_clock("05:30") == time(5, 30)
    assert parse_clock("9:00") == time(9, 0)


def test_logical_order_before_day_start_sorts_after_the_evening() -> None:
    # 00:30 "after midnight" belongs to the tail of the logical day, so it must
    # order after 23:00, not before 05:30.
    assert logical_order(time(0, 30), DAY_START) > logical_order(time(23, 0), DAY_START)
    assert logical_order(time(0, 30), DAY_START) > logical_order(time(5, 30), DAY_START)


def test_logical_order_day_start_is_the_earliest_point() -> None:
    assert logical_order(time(4, 0), DAY_START) < logical_order(time(4, 1), DAY_START)
    assert logical_order(time(3, 59), DAY_START) > logical_order(time(23, 0), DAY_START)


def test_date_from_md_same_year() -> None:
    assert date_from_md("03.13", date(2026, 3, 10)) == date(2026, 3, 13)


def test_date_from_md_wraps_to_next_year() -> None:
    assert date_from_md("01.01", date(2025, 12, 31)) == date(2026, 1, 1)


def test_date_from_md_wraps_to_previous_year() -> None:
    assert date_from_md("12.31", date(2026, 1, 1)) == date(2025, 12, 31)
