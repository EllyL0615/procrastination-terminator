"""Message tone: personality x intensity (SPEC §4.5). Pure -- no IO.

Personality is the flavour; intensity is the start-nagging escalation. Both are
derived deterministically so a task keeps a stable personality without storing
it, and the supervisor stays memoryless (intensity is a function of elapsed time).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from .config import PersonalityGranularity
from .models import Personality

_PERSONALITIES = tuple(Personality)


def intensity_for(elapsed: timedelta) -> int:
    """Escalation level from time since planned start: 0 (mild) .. 3 (most intense)."""
    minutes = int(elapsed.total_seconds() // 60)
    if minutes < 5:
        return 0
    if minutes < 15:
        return 1
    if minutes < 30:
        return 2
    return 3


def fixed_personality(seed: str) -> Personality:
    """Deterministically map a seed string to a personality (stable across runs)."""
    digest = hashlib.sha256(seed.encode()).digest()
    return _PERSONALITIES[digest[0] % len(_PERSONALITIES)]


def personality_for(
    granularity: PersonalityGranularity,
    *,
    code: str,
    day: str,
) -> Personality:
    """Pick a task's personality for the configured granularity (SPEC §4.5).

    ``PER_MESSAGE`` is re-rolled per message by the caller (not deterministic),
    so it is not handled here; this covers the stable PER_TASK / PER_DAY cases.
    """
    if granularity is PersonalityGranularity.PER_DAY:
        return fixed_personality(day)
    return fixed_personality(code)
