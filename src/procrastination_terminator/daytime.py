"""Logical-day ("作息日") helpers (SPEC §5, §3.2).

A logical day runs from ``day_start`` (default 04:00) to the next day's
``day_start``. A clock time earlier than ``day_start`` belongs to the *previous*
calendar day's logical day -- it is that day's "after midnight". This is what
makes a 23:00-01:00 task a single contiguous interval.

All datetimes here are timezone-aware; callers pass moments already expressed in
the target timezone (so the naive ``.time()`` comparison is meaningful).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo


def logical_day_of(moment: datetime, day_start: time) -> date:
    """Return the logical-day calendar date that ``moment`` falls in."""
    if moment.time() < day_start:
        return moment.date() - timedelta(days=1)
    return moment.date()


def resolve(logical_date: date, clock: time, day_start: time, tz: tzinfo) -> datetime:
    """Absolute tz-aware datetime for ``clock`` on logical day ``logical_date``.

    Clock times before ``day_start`` land on the next calendar day (after midnight).
    """
    calendar_date = logical_date + timedelta(days=1) if clock < day_start else logical_date
    return datetime.combine(calendar_date, clock, tzinfo=tz)


def midpoint(start: datetime, end: datetime) -> datetime:
    """Midpoint of the interval [``start``, ``end``]."""
    return start + (end - start) / 2
