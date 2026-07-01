"""Tests for loading Config from environment variables (SPEC §7).

The user tunes the bot without touching code, so every SPEC §7 knob must be
reachable from the environment; these pin the optional overrides and their
defaults.
"""

from __future__ import annotations

from datetime import time

import pytest

from procrastination_terminator.config import Config, PersonalityGranularity

_REQUIRED = {
    "DISCORD_TOKEN": "t",
    "DISCORD_USER_ID": "1",
    "DISCORD_CHANNEL_ID": "2",
    "LLM_API_KEY": "k",
    "LLM_BASE_URL": "http://localhost",
    "LLM_MODEL": "m",
}


def _set_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _REQUIRED.items():
        monkeypatch.setenv(key, value)


def test_defaults_without_optional_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    config = Config.from_env()
    assert config.day_start == time(4, 0)
    assert config.day_end == time(23, 0)
    assert config.poll_seconds == 60
    assert config.personality_granularity is PersonalityGranularity.PER_TASK
    assert config.progress_path == "data/progress.csv"


def test_schedule_and_paths_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.setenv("DAY_START", "05:30")
    monkeypatch.setenv("DAY_END", "23:45")
    monkeypatch.setenv("POLL_SECONDS", "30")
    monkeypatch.setenv("PERSONALITY_GRANULARITY", "per_day")
    monkeypatch.setenv("PLAN_PATH", "elsewhere/plan.txt")
    monkeypatch.setenv("PROGRESS_PATH", "elsewhere/progress.csv")
    monkeypatch.setenv("HISTORY_PATH", "elsewhere/history.csv")
    monkeypatch.setenv("CONTEXT_PATH", "elsewhere/context.txt")

    config = Config.from_env()

    assert config.day_start == time(5, 30)
    assert config.day_end == time(23, 45)
    assert config.poll_seconds == 30
    assert config.personality_granularity is PersonalityGranularity.PER_DAY
    assert config.plan_path == "elsewhere/plan.txt"
    assert config.progress_path == "elsewhere/progress.csv"
    assert config.history_path == "elsewhere/history.csv"
    assert config.context_path == "elsewhere/context.txt"


def test_missing_required_var_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required(monkeypatch)
    monkeypatch.delenv("DISCORD_TOKEN")
    with pytest.raises(RuntimeError, match="DISCORD_TOKEN"):
        Config.from_env()
