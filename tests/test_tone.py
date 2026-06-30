"""Tests for tone helpers (SPEC §4.5)."""

from __future__ import annotations

from datetime import timedelta

from procrastination_terminator.config import PersonalityGranularity
from procrastination_terminator.models import Personality
from procrastination_terminator.tone import (
    fixed_personality,
    intensity_for,
    personality_for,
)


def test_intensity_buckets() -> None:
    assert intensity_for(timedelta(minutes=0)) == 0
    assert intensity_for(timedelta(minutes=4, seconds=59)) == 0
    assert intensity_for(timedelta(minutes=5)) == 1
    assert intensity_for(timedelta(minutes=14)) == 1
    assert intensity_for(timedelta(minutes=15)) == 2
    assert intensity_for(timedelta(minutes=29)) == 2
    assert intensity_for(timedelta(minutes=30)) == 3
    assert intensity_for(timedelta(hours=3)) == 3


def test_fixed_personality_is_stable() -> None:
    assert fixed_personality("0313-1400-PGM") == fixed_personality("0313-1400-PGM")
    assert isinstance(fixed_personality("anything"), Personality)


def test_personality_per_task_keys_on_code() -> None:
    p1 = personality_for(PersonalityGranularity.PER_TASK, code="0313-1400-PGM", day="03.13")
    p2 = personality_for(PersonalityGranularity.PER_TASK, code="0313-1400-PGM", day="03.99")
    assert p1 == p2  # depends only on code


def test_personality_per_day_keys_on_day() -> None:
    p1 = personality_for(PersonalityGranularity.PER_DAY, code="0313-1400-PGM", day="03.13")
    p2 = personality_for(PersonalityGranularity.PER_DAY, code="9999-9999-XYZ", day="03.13")
    assert p1 == p2  # depends only on day
