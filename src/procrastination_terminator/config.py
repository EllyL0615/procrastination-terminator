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
    discord_channel_id: int
    llm_api_key: str
    llm_base_url: str
    llm_model: str
    bot_name: str = "Bot"
    timezone: str = "Europe/London"
    day_start: time = time(4, 0)
    day_end: time = time(23, 0)
    poll_seconds: int = 60
    personality_granularity: PersonalityGranularity = PersonalityGranularity.PER_TASK
    message_language: str = "en"
    dialogue_history_limit: int = 12  # recent DMs fed as context when writing a message (SPEC §4.5)
    plan_path: str = "data/plan.txt"
    progress_path: str = "data/progress.csv"
    history_path: str = "data/history.csv"
    context_path: str = "data/context.txt"  # user-written free-form notes fed to the LLM (SPEC §2)
    # Storage backend (SPEC §9): "file" (local, default) or "notion".
    storage_backend: str = "file"
    notion_api_key: str = ""
    notion_db_id: str = ""
    notion_plan_page_id: str = ""
    notion_context_page_id: str = ""

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

        config = cls(
            discord_token=_require("DISCORD_TOKEN"),
            discord_user_id=int(_require("DISCORD_USER_ID")),
            discord_channel_id=int(_require("DISCORD_CHANNEL_ID")),
            llm_api_key=_require("LLM_API_KEY"),
            llm_base_url=_require("LLM_BASE_URL"),
            llm_model=_require("LLM_MODEL"),
            bot_name=os.environ.get("BOT_NAME", "Bot"),
            timezone=os.environ.get("TIMEZONE", "Europe/London"),
            message_language=os.environ.get("MESSAGE_LANG", "en"),
            dialogue_history_limit=int(os.environ.get("DIALOGUE_HISTORY", "12")),
            storage_backend=os.environ.get("STORAGE_BACKEND", "file"),
            notion_api_key=os.environ.get("NOTION_API_KEY", ""),
            notion_db_id=os.environ.get("NOTION_DB_ID", ""),
            notion_plan_page_id=os.environ.get("NOTION_PLAN_PAGE_ID", ""),
            notion_context_page_id=os.environ.get("NOTION_CONTEXT_PAGE_ID", ""),
        )
        if config.storage_backend == "notion":
            missing = [
                name
                for name, value in (
                    ("NOTION_API_KEY", config.notion_api_key),
                    ("NOTION_DB_ID", config.notion_db_id),
                    ("NOTION_PLAN_PAGE_ID", config.notion_plan_page_id),
                    ("NOTION_CONTEXT_PAGE_ID", config.notion_context_page_id),
                )
                if not value
            ]
            if missing:
                raise RuntimeError(f"STORAGE_BACKEND=notion requires: {', '.join(missing)}")
        return config
