"""Tests for the pure LLM-output parsing helper and the user-context injection.

The HTTP calls themselves are IO (SPEC §9); here we pin the JSON parsing and the
standing-context folding done in ``_augment`` (SPEC §2, §4.5) -- both pure/local.
The context now arrives from an injected provider (the storage backend); reading
it from a file is covered in test_file_backend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from procrastination_terminator.config import Config
from procrastination_terminator.llm import LLMClient, _extract_json


def test_plain_json() -> None:
    assert _extract_json('{"yes": true}') == {"yes": True}


def test_fenced_json() -> None:
    assert _extract_json('```json\n{"code": "0313-1400-PGM"}\n```') == {"code": "0313-1400-PGM"}


def test_fenced_without_language_tag() -> None:
    assert _extract_json('```\n{"type": "study"}\n```') == {"type": "study"}


def test_surrounding_whitespace() -> None:
    assert _extract_json('  \n{"yes": false}\n  ') == {"yes": False}


def test_non_object_rejected() -> None:
    with pytest.raises(ValueError, match="expected a JSON object"):
        _extract_json("[1, 2, 3]")


def _client(context: Callable[[], str]) -> LLMClient:
    """An LLMClient whose only exercised knob is the injected context provider."""
    config = Config(
        discord_token="t",
        discord_user_id=1,
        discord_channel_id=2,
        llm_api_key="k",
        llm_base_url="http://localhost",
        llm_model="m",
    )
    return LLMClient(config, context_provider=context)


def test_augment_appends_user_context() -> None:
    client = _client(lambda: "Game = 博弈论课程")
    try:
        result = client._augment("TASK RULES")
    finally:
        asyncio.run(client.aclose())
    assert result.startswith("TASK RULES")  # original system prompt stays on top
    assert "Game = 博弈论课程" in result


def test_augment_is_noop_without_context() -> None:
    client = _client(lambda: "")
    try:
        assert client._augment("TASK RULES") == "TASK RULES"
    finally:
        asyncio.run(client.aclose())


def test_augment_is_noop_when_context_blank() -> None:
    client = _client(lambda: "  \n\t\n")
    try:
        assert client._augment("TASK RULES") == "TASK RULES"
    finally:
        asyncio.run(client.aclose())
