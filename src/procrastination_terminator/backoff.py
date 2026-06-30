"""Start-nagging backoff curve (SPEC §7, §4.1).

The monitor is stateless: whether a given minute should fire a nag is a pure
function of ``m`` = whole minutes elapsed since the task's planned start. Each
phase is anchored at its lower bound, so the first minute of every phase always
nags and there is no gap at a phase boundary.

    m in [0, 5)   -> every 1 min  -> 0, 1, 2, 3, 4
    m in [5, 15)  -> every 3 min  -> 5, 8, 11, 14
    m in [15, 30) -> every 5 min  -> 15, 20, 25
    m >= 30       -> every 10 min -> 30, 40, 50, ...
"""

from __future__ import annotations

from datetime import timedelta

# (exclusive upper bound, interval); each phase is anchored at the previous bound.
_PHASES: tuple[tuple[int, int], ...] = ((5, 1), (15, 3), (30, 5))
_TAIL_INTERVAL = 10  # applies to m >= 30


def is_nag_minute(m: int) -> bool:
    """Whether minute ``m`` (>= 0) since planned start is a nag minute."""
    if m < 0:
        return False
    lower = 0
    for upper, interval in _PHASES:
        if m < upper:
            return (m - lower) % interval == 0
        lower = upper
    return (m - lower) % _TAIL_INTERVAL == 0


def should_nag(elapsed: timedelta) -> bool:
    """Whether to nag at ``elapsed`` since planned start (negative -> no)."""
    return is_nag_minute(int(elapsed.total_seconds() // 60))
