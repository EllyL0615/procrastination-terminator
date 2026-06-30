"""Logical-day helpers (SPEC §5, §3.2).

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


def date_from_md(md: str, reference: date) -> date:
    """Resolve a yearless ``"MM.DD"`` to the calendar date closest to ``reference``.

    plan.txt dates carry no year; pick the year (within +/-1 of ``reference``)
    that lands nearest the reference date, so end-of-year wrap resolves sanely.
    """
    month, day = (int(part) for part in md.split("."))
    candidates: list[date] = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue  # e.g. 02.29 in a non-leap year
    return min(candidates, key=lambda d: abs((d - reference).days))
