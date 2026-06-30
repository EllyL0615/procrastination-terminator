"""Tests for the backoff curve (SPEC §7, §4.1)."""

from __future__ import annotations

from datetime import timedelta

from procrastination_terminator.backoff import is_nag_minute, should_nag

# The exact set of nag minutes in the first hour, per the anchored curve.
EXPECTED_NAG_MINUTES = {0, 1, 2, 3, 4, 5, 8, 11, 14, 15, 20, 25, 30, 40, 50, 60}


def test_nag_minutes_in_first_hour() -> None:
    got = {m for m in range(61) if is_nag_minute(m)}
    assert got == EXPECTED_NAG_MINUTES


def test_first_minute_of_each_phase_nags() -> None:
    for anchor in (0, 5, 15, 30):
        assert is_nag_minute(anchor)


def test_negative_minutes_never_nag() -> None:
    assert not is_nag_minute(-1)
    assert not should_nag(timedelta(minutes=-3))


def test_should_nag_floors_to_minutes() -> None:
    assert should_nag(timedelta(minutes=8, seconds=59))  # still minute 8
    assert not should_nag(timedelta(minutes=9))  # minute 9 is off-curve
