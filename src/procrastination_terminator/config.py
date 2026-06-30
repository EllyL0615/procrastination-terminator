"""Runtime configuration (SPEC §7), loaded from environment variables."""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo


class PersonalityGranularity(enum.Enum):
    """How often the message personality is (re)chosen (SPEC §4.5)."""

    PER_TASK = "per_task"
    PER_MESSAGE = "per_message"
    PER_DAY = "per_day"


@dataclass(frozen=True)
class Config:
    """All knobs from SPEC §7 plus the secrets needed to connect."""

    discord_token: str
    discord_user_id: int
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    bot_name: str = "Bot"
    timezone: str = "Europe/London"
    day_start: time = time(4, 0)
    day_end: time = time(23, 0)
    poll_seconds: int = 60
    personality_granularity: PersonalityGranularity = PersonalityGranularity.PER_TASK
    plan_path: str = "data/plan.txt"
    progress_path: str = "data/progress.csv"
    history_path: str = "data/history.csv"

    @property
    def tz(self) -> ZoneInfo:
        """The timezone object; handles BST/GMT DST automatically (SPEC §7)."""
        return ZoneInfo(self.timezone)

    @classmethod
    def from_env(cls) -> Config:
        """Build a Config from environment variables (see .env.example)."""

        def _require(key: str) -> str:
            value = os.environ.get(key)
            if not value:
                raise RuntimeError(f"missing required env var: {key}")
            return value

        return cls(
            discord_token=_require("DISCORD_TOKEN"),
            discord_user_id=int(_require("DISCORD_USER_ID")),
            llm_api_key=_require("LLM_API_KEY"),
            llm_base_url=_require("LLM_BASE_URL"),
            llm_model=_require("LLM_MODEL"),
            bot_name=os.environ.get("BOT_NAME", "Bot"),
            timezone=os.environ.get("TIMEZONE", "Europe/London"),
        )
