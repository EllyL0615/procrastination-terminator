"""Offline tests for the init-notion provisioning command (SPEC §9).

No network (httpx.MockTransport). We pin the model-derived schema, that the
command creates the database and both pages, and the security contract: the
token comes only from NOTION_API_KEY and never appears in the printed output.
"""

from __future__ import annotations

import httpx
import pytest

from procrastination_terminator.models import CSV_COLUMNS, Status, TaskType
from procrastination_terminator.notion_init import (
    _database_properties,
    _normalize_page_id,
    init_notion,
)

_TOKEN = "ntn_secret_value"
_PARENT_ID = "0123456789abcdef0123456789abcdef"


def test_database_properties_match_the_model() -> None:
    props = _database_properties()
    assert set(props) == set(CSV_COLUMNS) | {"archived"}
    assert props["code"] == {"title": {}}
    assert props["archived"] == {"checkbox": {}}
    assert props["date"] == {"rich_text": {}}
    type_options = {o["name"] for o in props["type"]["select"]["options"]}
    status_options = {o["name"] for o in props["status"]["select"]["options"]}
    assert type_options == {t.value for t in TaskType}
    assert status_options == {s.value for s in Status}


def test_database_select_options_carry_colors() -> None:
    # Status colors mirror the !progress emoji semantics (⬜🟥🟨✅, SPEC §6).
    props = _database_properties()
    status_colors = {o["name"]: o["color"] for o in props["status"]["select"]["options"]}
    type_colors = {o["name"]: o["color"] for o in props["type"]["select"]["options"]}
    assert status_colors == {
        "todo": "gray",
        "overdue": "red",
        "started": "orange",
        "completed": "green",
    }
    assert type_colors == {"study": "blue", "work": "blue", "outing": "yellow", "other": "gray"}


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.auth: list[str] = []
        self._seq = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        self.auth.append(request.headers.get("authorization", ""))
        self._seq += 1
        return httpx.Response(200, json={"id": f"id-{self._seq}"})


def test_init_creates_database_and_pages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NOTION_API_KEY", _TOKEN)
    recorder = _Recorder()
    init_notion([_PARENT_ID], transport=httpx.MockTransport(recorder.handler))
    assert recorder.calls == [
        ("POST", "/v1/databases"),
        ("POST", "/v1/pages"),
        ("POST", "/v1/pages"),
    ]
    out = capsys.readouterr().out
    assert "NOTION_DB_ID=id-1" in out
    assert "NOTION_PLAN_PAGE_ID=id-2" in out
    assert "NOTION_CONTEXT_PAGE_ID=id-3" in out
    # security: the token authenticated every call but was never printed
    assert all(value == f"Bearer {_TOKEN}" for value in recorder.auth)
    assert _TOKEN not in out


def test_init_requires_token_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="NOTION_API_KEY"):
        init_notion(["PARENT"])


def test_init_rejects_wrong_arg_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTION_API_KEY", _TOKEN)
    with pytest.raises(SystemExit, match="usage"):
        init_notion([])


def test_notion_error_surfaces_message_without_leaking_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOTION_API_KEY", _TOKEN)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "API token is invalid."})

    with pytest.raises(SystemExit, match="API token is invalid") as exc:
        init_notion([_PARENT_ID], transport=httpx.MockTransport(handler))
    assert _TOKEN not in str(exc.value)


def test_normalize_page_id_from_copy_link_url() -> None:
    url = "https://app.notion.com/p/Procrastination-Terminator-0123456789abcdef0123456789abcdef?source=copy_link"
    assert _normalize_page_id(url) == "01234567-89ab-cdef-0123-456789abcdef"


def test_normalize_page_id_from_bare_hex() -> None:
    assert (
        _normalize_page_id("0123456789abcdef0123456789abcdef")
        == "01234567-89ab-cdef-0123-456789abcdef"
    )


def test_normalize_page_id_passes_through_dashed_uuid() -> None:
    uuid = "01234567-89ab-cdef-0123-456789abcdef"
    assert _normalize_page_id(uuid) == uuid


def test_normalize_page_id_rejects_garbage() -> None:
    with pytest.raises(SystemExit, match="could not find"):
        _normalize_page_id("not-a-notion-page")
