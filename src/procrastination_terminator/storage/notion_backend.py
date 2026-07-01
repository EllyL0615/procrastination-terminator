"""Notion storage backend (SPEC §3, §9): the single source of truth lives in Notion.

progress and history share ONE database; a row's ``archived`` checkbox is the
today-vs-history split (the working set is ``archived == false``), so day-start
archiving is just a checkbox flip -- no cross-database move, nothing to half-apply.
plan.txt and context.txt each become a Notion page whose text blocks are read and
joined. Every field maps to a Notion property (title/rich_text/select); the
``code`` title is the sync identity. Writes are per-page, matched by ``code``, so
a manual edit to another row is never clobbered (SPEC §3.2, A6) -- Notion updates
only the properties sent.

The user is one person and the tick is 60s, so request volume is tiny; a 429 is
honoured with its ``Retry-After`` and retried a few times. ``context`` is read
every LLM call, so it is cached and only refreshed on demand (startup / day-start
/ an explicit reload), never per call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

import httpx

from .. import daytime
from ..config import Config
from ..models import Status, Task, TaskType
from ..store import _join_range, _split_range

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_MAX_RETRIES = 4

# Block types whose text is part of the plan/context prose (others are ignored).
_TEXT_BLOCKS = frozenset(
    {
        "paragraph",
        "heading_1",
        "heading_2",
        "heading_3",
        "bulleted_list_item",
        "numbered_list_item",
        "to_do",
        "quote",
    }
)


class NotionError(RuntimeError):
    """A Notion API call failed; carries Notion's error message when available."""


class NotionBackend:
    """StorageBackend backed by a Notion database (tasks) plus two text pages."""

    def __init__(self, config: Config, client: httpx.AsyncClient | None = None) -> None:
        self._db_id = config.notion_db_id
        self._plan_page_id = config.notion_plan_page_id
        self._context_page_id = config.notion_context_page_id
        self._day_start = config.day_start
        self._http = client or httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.notion_api_key}",
                "Notion-Version": _NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._context = ""

    # -- StorageBackend interface -------------------------------------------

    async def load_progress(self) -> list[Task]:
        # Notion query order is not guaranteed, so sort by logical day here to match
        # the file backend (kept physically sorted on write). The monitor re-sorts its
        # own working set, but !progress and the day-end summary read this order.
        tasks = [self._props_to_task(page) for page in await self._query_active_pages()]
        return sorted(tasks, key=self._order_key)

    def _order_key(self, task: Task) -> tuple[str, int]:
        try:
            minutes = daytime.logical_order(
                daytime.parse_clock(task.planned_start), self._day_start
            )
        except ValueError:
            minutes = 0
        return (task.date, minutes)

    async def upsert_changed(self, changed: Iterable[Task]) -> None:
        updates = list(changed)
        if not updates:
            return
        page_ids = await self._active_page_ids()
        for task in updates:
            await self._write_task(task, page_ids.get(task.code))

    async def write_all(self, tasks: list[Task]) -> None:
        page_ids = await self._active_page_ids()
        target = {t.code: t for t in tasks}
        for task in target.values():
            await self._write_task(task, page_ids.get(task.code))
        for code, page_id in page_ids.items():
            if code not in target:  # dropped from the plan: trash the page (recoverable)
                await self._request("PATCH", f"/pages/{page_id}", json={"archived": True})

    async def archive_past(self, current_logical_day: str) -> None:
        for page in await self._query_active_pages():
            if self._rich(page["properties"], "date") < current_logical_day:
                await self._request(
                    "PATCH",
                    f"/pages/{page['id']}",
                    json={"properties": {"archived": {"checkbox": True}}},
                )

    async def read_plan(self) -> str:
        return await self._page_text(self._plan_page_id)

    async def refresh_context(self) -> None:
        self._context = await self._page_text(self._context_page_id)

    def current_context(self) -> str:
        return self._context

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- Notion queries / writes --------------------------------------------

    async def _query_active_pages(self) -> list[dict[str, Any]]:
        """Every non-archived task page (the today-and-future working set)."""
        payload: dict[str, Any] = {
            "filter": {"property": "archived", "checkbox": {"equals": False}}
        }
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body = {**payload, "start_cursor": cursor} if cursor else payload
            data = await self._request("POST", f"/databases/{self._db_id}/query", json=body)
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                return pages
            cursor = data.get("next_cursor")

    async def _active_page_ids(self) -> dict[str, str]:
        return {
            self._title(page["properties"], "code"): str(page["id"])
            for page in await self._query_active_pages()
        }

    async def _write_task(self, task: Task, page_id: str | None) -> None:
        """Update the page for this code, or create it if new (matched by code)."""
        props = self._task_to_props(task)
        if page_id is None:
            await self._request(
                "POST", "/pages", json={"parent": {"database_id": self._db_id}, "properties": props}
            )
        else:
            await self._request("PATCH", f"/pages/{page_id}", json={"properties": props})

    async def _page_text(self, page_id: str) -> str:
        """Join the plain text of a page's prose blocks, one block per line."""
        lines: list[str] = []
        cursor: str | None = None
        while True:
            params = {"start_cursor": cursor} if cursor else None
            data = await self._request("GET", f"/blocks/{page_id}/children", params=params)
            for block in data.get("results", []):
                text = self._block_text(block)
                if text is not None:
                    lines.append(text)
            if not data.get("has_more"):
                return "\n".join(lines)
            cursor = data.get("next_cursor")

    # -- serialisation (parallels store._to_row / _from_row) ----------------

    def _task_to_props(self, task: Task) -> dict[str, Any]:
        # ``archived`` is owned by archive_past/write_all, never touched here, so an
        # upsert can't flip a row's today/history state (SPEC §3.1).
        return {
            "code": {"title": self._text(task.code)},
            "date": {"rich_text": self._text(task.date)},
            "planned_time": {"rich_text": self._text(f"{task.planned_start}-{task.planned_end}")},
            "task": {"rich_text": self._text(task.description)},
            "notes": {"rich_text": self._text(task.notes)},
            "type": {"select": {"name": task.type.value}},
            "status": {"select": {"name": task.status.value}},
            "actual_time": {
                "rich_text": self._text(_join_range(task.actual_start, task.actual_end))
            },
            "latest_progress": {"rich_text": self._text(task.latest_progress)},
            "latest_progress_time": {"rich_text": self._text(task.latest_progress_time or "")},
        }

    def _props_to_task(self, page: dict[str, Any]) -> Task:
        props = page["properties"]
        planned_start, planned_end = _split_range(self._rich(props, "planned_time"))
        actual_start, actual_end = _split_range(self._rich(props, "actual_time"))
        return Task(
            code=self._title(props, "code"),
            date=self._rich(props, "date"),
            planned_start=planned_start or "",
            planned_end=planned_end or "",
            description=self._rich(props, "task"),
            notes=self._rich(props, "notes"),
            type=TaskType(self._select(props, "type")),
            status=Status(self._select(props, "status")),
            actual_start=actual_start,
            actual_end=actual_end,
            latest_progress=self._rich(props, "latest_progress"),
            latest_progress_time=self._rich(props, "latest_progress_time") or None,
        )

    @staticmethod
    def _text(content: str) -> list[dict[str, Any]]:
        """Notion rich_text/title value for a plain string ('' -> empty array)."""
        return [{"text": {"content": content}}] if content else []

    @staticmethod
    def _title(props: dict[str, Any], name: str) -> str:
        return "".join(str(p.get("plain_text", "")) for p in props.get(name, {}).get("title", []))

    @staticmethod
    def _rich(props: dict[str, Any], name: str) -> str:
        return "".join(
            str(p.get("plain_text", "")) for p in props.get(name, {}).get("rich_text", [])
        )

    @staticmethod
    def _select(props: dict[str, Any], name: str) -> str:
        selected = props.get(name, {}).get("select")
        return str(selected["name"]) if selected else ""

    @staticmethod
    def _block_text(block: dict[str, Any]) -> str | None:
        block_type = str(block.get("type", ""))
        if block_type not in _TEXT_BLOCKS:
            return None
        rich = block.get(block_type, {}).get("rich_text", [])
        return "".join(str(part.get("plain_text", "")) for part in rich)

    # -- HTTP with 429 backoff ----------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        for _ in range(_MAX_RETRIES):
            response = await self._http.request(method, path, json=json, params=params)
            if response.status_code == 429:
                await asyncio.sleep(float(response.headers.get("Retry-After", "1")))
                continue
            if response.status_code >= 400:
                raise NotionError(self._error_message(response))
            result: dict[str, Any] = response.json()
            return result
        raise NotionError("Notion rate limit: retries exhausted")

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        return (
            str(payload.get("message", response.text))
            if isinstance(payload, dict)
            else response.text
        )
