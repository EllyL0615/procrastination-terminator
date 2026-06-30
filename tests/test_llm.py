"""Tests for the pure LLM-output parsing helper. The HTTP calls are IO (SPEC §9)."""

from __future__ import annotations

import pytest

from procrastination_terminator.llm import _extract_json


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
