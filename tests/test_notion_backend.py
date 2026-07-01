"""Offline tests for NotionBackend (SPEC §3, §9).

No network: an in-memory ``_FakeNotion`` answers the REST calls through
``httpx.MockTransport``. We pin the property serialisation both ways, the four
operations' round-trip behaviour (create/update/trash/archive), the block-text
join, the context cache, and the 429 retry.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from typing import Any

import httpx

from procrastination_terminator.config import Config
from procrastination_terminator.models import Status, Task, TaskType
from procrastination_terminator.storage.notion_backend import _BASE_URL, NotionBackend


class _FakeNotion:
    """A tiny in-memory Notion: a task database plus fixed page blocks."""

    def __init__(self, blocks: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.pages: dict[str, dict[str, Any]] = {}  # id -> {properties, trashed}
        self._blocks = blocks or {}
        self._seq = 0
        self.requests: list[str] = []  # "METHOD path" log, for asserting call shape

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.requests.append(f"{method} {path}")
        body = json.loads(request.content) if request.content else {}
        if method == "POST" and path.endswith("/query"):
            results = [
                {"id": pid, "properties": page["properties"]}
                for pid, page in self.pages.items()
                if not page["trashed"] and not self._is_archived(page)
            ]
            return httpx.Response(200, json={"results": results, "has_more": False})
        if method == "POST" and path == "/v1/pages":
            self._seq += 1
            pid = f"page-{self._seq}"
            self.pages[pid] = {
                "properties": self._read_format(body["properties"]),
                "trashed": False,
            }
            return httpx.Response(200, json={"id": pid})
        if method == "PATCH" and path.startswith("/v1/pages/"):
            page = self.pages[path.rsplit("/", 1)[-1]]
            if body.get("archived") is True:
                page["trashed"] = True
            if "properties" in body:
                page["properties"].update(self._read_format(body["properties"]))
            return httpx.Response(200, json={"id": "ok"})
        if method == "GET" and path.endswith("/children"):
            pid = path.split("/blocks/")[1].split("/children")[0]
            return httpx.Response(
                200, json={"results": self._blocks.get(pid, []), "has_more": False}
            )
        return httpx.Response(404, json={"message": f"no route {method} {path}"})

    @staticmethod
    def _is_archived(page: dict[str, Any]) -> bool:
        return bool(page["properties"].get("archived", {}).get("checkbox"))

    @staticmethod
    def _read_format(props: dict[str, Any]) -> dict[str, Any]:
        """Echo a write payload back as Notion would read it (content -> plain_text)."""
        out: dict[str, Any] = {}
        for name, value in props.items():
            if "title" in value:
                out[name] = {
                    "title": [{"plain_text": i["text"]["content"]} for i in value["title"]]
                }
            elif "rich_text" in value:
                out[name] = {
                    "rich_text": [{"plain_text": i["text"]["content"]} for i in value["rich_text"]]
                }
            else:
                out[name] = value  # select / checkbox pass through unchanged
        return out


def _backend(fake: _FakeNotion, client: httpx.AsyncClient | None = None) -> NotionBackend:
    config = Config(
        discord_token="t",
        discord_user_id=1,
        discord_channel_id=2,
        llm_api_key="k",
        llm_base_url="http://localhost",
        llm_model="m",
        storage_backend="notion",
        notion_db_id="DB",
        notion_plan_page_id="PLAN",
        notion_context_page_id="CTX",
    )
    client = client or httpx.AsyncClient(
        base_url=_BASE_URL, transport=httpx.MockTransport(fake.handler)
    )
    return NotionBackend(config, client=client)


def _task(code: str = "0701-1400-GAME", date: str = "07.01", **kw: Any) -> Task:
    base: dict[str, Any] = {
        "code": code,
        "date": date,
        "planned_start": "14:00",
        "planned_end": "15:00",
        "description": "Game Chap1",
        "type": TaskType.STUDY,
        "status": Status.NOT_STARTED,
        "notes": "30min problems",
    }
    base.update(kw)
    return Task(**base)


def _text_block(block_type: str, text: str) -> dict[str, Any]:
    return {"type": block_type, block_type: {"rich_text": [{"plain_text": text}]}}


# -- serialisation ----------------------------------------------------------


def test_props_to_task_maps_all_fields() -> None:
    backend = _backend(_FakeNotion())
    page = {
        "id": "p1",
        "properties": {
            "code": {"title": [{"plain_text": "0701-1400-GAME"}]},
            "date": {"rich_text": [{"plain_text": "07.01"}]},
            "planned_time": {"rich_text": [{"plain_text": "14:00-15:00"}]},
            "task": {"rich_text": [{"plain_text": "Game Chap1"}]},
            "notes": {"rich_text": [{"plain_text": "30min problems"}]},
            "type": {"select": {"name": "study"}},
            "status": {"select": {"name": "started"}},
            "actual_time": {"rich_text": [{"plain_text": "14:05-"}]},
            "latest_progress": {"rich_text": [{"plain_text": "did q1"}]},
            "latest_progress_time": {"rich_text": [{"plain_text": "2026-07-01T14:05:00"}]},
        },
    }
    task = backend._props_to_task(page)
    asyncio.run(backend.aclose())
    assert task.code == "0701-1400-GAME"
    assert task.date == "07.01"
    assert (task.planned_start, task.planned_end) == ("14:00", "15:00")
    assert task.notes == "30min problems"
    assert task.type is TaskType.STUDY
    assert task.status is Status.IN_PROGRESS  # "started" -> IN_PROGRESS
    assert (task.actual_start, task.actual_end) == ("14:05", None)
    assert task.latest_progress == "did q1"
    assert task.latest_progress_time == "2026-07-01T14:05:00"


def test_task_to_props_maps_all_fields() -> None:
    backend = _backend(_FakeNotion())
    props = backend._task_to_props(_task(status=Status.NOT_STARTED))
    asyncio.run(backend.aclose())
    assert props["code"]["title"][0]["text"]["content"] == "0701-1400-GAME"
    assert props["status"]["select"]["name"] == "todo"  # NOT_STARTED serialises as todo
    assert props["type"]["select"]["name"] == "study"
    assert props["planned_time"]["rich_text"][0]["text"]["content"] == "14:00-15:00"
    assert props["notes"]["rich_text"][0]["text"]["content"] == "30min problems"
    assert "archived" not in props  # owned by archive_past/write_all, never by an upsert


def test_empty_rich_text_is_empty_array() -> None:
    backend = _backend(_FakeNotion())
    props = backend._task_to_props(_task(notes="", latest_progress="", latest_progress_time=None))
    asyncio.run(backend.aclose())
    assert props["notes"]["rich_text"] == []
    assert props["latest_progress_time"]["rich_text"] == []


# -- operations round-trip --------------------------------------------------


def test_load_empty_returns_empty() -> None:
    async def scenario() -> list[Task]:
        backend = _backend(_FakeNotion())
        try:
            return await backend.load_progress()
        finally:
            await backend.aclose()

    assert asyncio.run(scenario()) == []


def test_upsert_creates_then_updates_in_place() -> None:
    fake = _FakeNotion()

    async def scenario() -> list[Task]:
        backend = _backend(fake)
        try:
            await backend.upsert_changed([_task()])
            done = _task(status=Status.COMPLETED)
            await backend.upsert_changed([done])  # same code -> update, not a second row
            return await backend.load_progress()
        finally:
            await backend.aclose()

    loaded = asyncio.run(scenario())
    assert len(loaded) == 1
    assert loaded[0].status is Status.COMPLETED


def test_upsert_preserves_other_rows() -> None:
    fake = _FakeNotion()

    async def scenario() -> dict[str, Task]:
        backend = _backend(fake)
        try:
            await backend.upsert_changed([_task("0701-1400-GAME"), _task("0701-1500-MATH")])
            await backend.upsert_changed([_task("0701-1400-GAME", status=Status.COMPLETED)])
            return {t.code: t for t in await backend.load_progress()}
        finally:
            await backend.aclose()

    loaded = asyncio.run(scenario())
    assert loaded["0701-1400-GAME"].status is Status.COMPLETED
    assert loaded["0701-1500-MATH"].status is Status.NOT_STARTED


def test_write_all_trashes_dropped_codes() -> None:
    fake = _FakeNotion()

    async def scenario() -> list[str]:
        backend = _backend(fake)
        try:
            await backend.upsert_changed([_task("0701-1400-GAME"), _task("0701-1500-MATH")])
            await backend.write_all([_task("0701-1400-GAME")])  # MATH dropped
            return [t.code for t in await backend.load_progress()]
        finally:
            await backend.aclose()

    assert asyncio.run(scenario()) == ["0701-1400-GAME"]


def test_archive_past_flips_checkbox_out_of_working_set() -> None:
    fake = _FakeNotion()

    async def scenario() -> list[str]:
        backend = _backend(fake)
        try:
            await backend.upsert_changed(
                [_task("0630-1400-OLD", "06.30"), _task("0701-1400-GAME", "07.01")]
            )
            await backend.archive_past(datetime.date(2026, 7, 1))
            return [t.code for t in await backend.load_progress()]
        finally:
            await backend.aclose()

    assert asyncio.run(scenario()) == ["0701-1400-GAME"]


# -- pages: plan / context --------------------------------------------------


def test_read_plan_joins_block_text() -> None:
    fake = _FakeNotion(
        blocks={
            "PLAN": [
                _text_block("heading_1", "07.01"),
                _text_block("paragraph", "14:00 Game Chap1"),
                {"type": "divider", "divider": {}},  # non-text block ignored
                _text_block("bulleted_list_item", "15:00 Math"),
            ]
        }
    )

    async def scenario() -> str:
        backend = _backend(fake)
        try:
            return await backend.read_plan()
        finally:
            await backend.aclose()

    assert asyncio.run(scenario()) == "07.01\n14:00 Game Chap1\n15:00 Math"


def test_refresh_context_caches_and_serves_without_new_request() -> None:
    fake = _FakeNotion(blocks={"CTX": [_text_block("paragraph", "Game = 博弈论课程")]})

    async def scenario() -> tuple[str, int]:
        backend = _backend(fake)
        try:
            assert backend.current_context() == ""  # nothing cached yet
            await backend.refresh_context()
            after_refresh = len(fake.requests)
            cached = backend.current_context()  # must not hit the network
            assert len(fake.requests) == after_refresh
            return cached, after_refresh
        finally:
            await backend.aclose()

    cached, requests_after_refresh = asyncio.run(scenario())
    assert cached == "Game = 博弈论课程"
    assert requests_after_refresh == 1  # exactly one GET to fill the cache


# -- 429 handling -----------------------------------------------------------


def test_429_is_retried_then_succeeds() -> None:
    state = {"first": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["first"]:
            state["first"] = False
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "slow down"})
        return httpx.Response(200, json={"results": [], "has_more": False})

    async def scenario() -> list[Task]:
        backend = _backend(
            _FakeNotion(),
            httpx.AsyncClient(base_url=_BASE_URL, transport=httpx.MockTransport(handler)),
        )
        try:
            return await backend.load_progress()
        finally:
            await backend.aclose()

    assert asyncio.run(scenario()) == []  # recovered on the retry
    assert state["first"] is False


def test_load_progress_sorts_by_logical_day() -> None:
    fake = _FakeNotion()

    async def scenario() -> list[str]:
        backend = _backend(fake)
        try:
            await backend.upsert_changed(
                [
                    _task("0701-2300-SLEEP", planned_start="23:00", planned_end="01:00"),
                    _task("0701-2400-MID", planned_start="00:00", planned_end="08:00"),
                    _task("0701-1400-GAME", planned_start="14:00", planned_end="15:00"),
                ]
            )
            return [t.code for t in await backend.load_progress()]
        finally:
            await backend.aclose()

    # Rows sort by code; 00:00's code is 2400, so it trails the logical day.
    assert asyncio.run(scenario()) == [
        "0701-1400-GAME",
        "0701-2300-SLEEP",
        "0701-2400-MID",
    ]
