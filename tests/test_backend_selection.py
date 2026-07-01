"""build_backend selection and notion-config validation (SPEC §9)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from procrastination_terminator.config import Config
from procrastination_terminator.storage import FileBackend, NotionBackend, build_backend

_REQUIRED = {
    "DISCORD_TOKEN": "t",
    "DISCORD_USER_ID": "1",
    "DISCORD_CHANNEL_ID": "2",
    "LLM_API_KEY": "k",
    "LLM_BASE_URL": "http://localhost",
    "LLM_MODEL": "m",
}
_NOTION = {
    "NOTION_API_KEY": "key",
    "NOTION_DB_ID": "db",
    "NOTION_PLAN_PAGE_ID": "plan",
    "NOTION_CONTEXT_PAGE_ID": "ctx",
}


def _config(**kw: Any) -> Config:
    base: dict[str, Any] = {
        "discord_token": "t",
        "discord_user_id": 1,
        "discord_channel_id": 2,
        "llm_api_key": "k",
        "llm_base_url": "http://localhost",
        "llm_model": "m",
    }
    base.update(kw)
    return Config(**base)


def test_build_backend_defaults_to_file() -> None:
    assert isinstance(build_backend(_config()), FileBackend)


def test_build_backend_notion() -> None:
    backend = build_backend(
        _config(
            storage_backend="notion",
            notion_db_id="DB",
            notion_plan_page_id="P",
            notion_context_page_id="C",
        )
    )
    assert isinstance(backend, NotionBackend)
    asyncio.run(backend.aclose())


def test_build_backend_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown STORAGE_BACKEND"):
        build_backend(_config(storage_backend="sqlite"))


def _set_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for key in (*_REQUIRED, *_NOTION):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_from_env_notion_requires_all_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, {**_REQUIRED, "STORAGE_BACKEND": "notion"})  # no NOTION_* set
    with pytest.raises(RuntimeError, match="STORAGE_BACKEND=notion requires"):
        Config.from_env()


def test_from_env_notion_ok_with_all_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, {**_REQUIRED, **_NOTION, "STORAGE_BACKEND": "notion"})
    config = Config.from_env()
    assert config.storage_backend == "notion"
    assert config.notion_db_id == "db"


def test_from_env_file_mode_ignores_missing_notion(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, _REQUIRED)  # STORAGE_BACKEND unset -> file
    config = Config.from_env()
    assert config.storage_backend == "file"
