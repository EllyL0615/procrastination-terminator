"""One-shot Notion provisioning: ``python -m procrastination_terminator init-notion <parent_page_id>``.

Builds the ``tasks`` database (schema derived from the model, so it can't drift
from what :mod:`.storage.notion_backend` reads/writes) plus empty ``plan`` and
``context`` pages under a parent page you already shared with your connection,
then prints the three ids to paste into ``.env``.

Security contract for the Notion token:
- read ONLY from ``NOTION_API_KEY`` (env / .env); never a CLI argument, which
  would leak into shell history and the process list;
- used solely in the ``Authorization`` header; never printed, logged, or written;
- on error only Notion's ``message`` is surfaced, never the raw request/headers.
Command output is only the non-secret ids it created.
"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from .models import CSV_COLUMNS, Status, TaskType

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_USAGE = "usage: python -m procrastination_terminator init-notion <parent_page_id>"

_PLAN_HINT = (
    "Write your daily plan here: a date line like '07.01', then time lines like '14:00 Game Chap1'."
)
_CONTEXT_HINT = "Standing context for the bot (glossary / tone / facts about you), e.g. 'Game = a course, not video games'."


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX32_RE = re.compile(r"[0-9a-fA-F]{32}")


def _normalize_page_id(value: str) -> str:
    """Accept a full Notion URL, a bare 32-char id, or a dashed UUID; return a UUID.

    A Copy-link URL looks like ``.../Title-<32 hex>?source=...``; the id is those 32
    hex chars. Notion's API wants a UUID, so format them 8-4-4-4-12.
    """
    text = value.strip()
    dashed = _UUID_RE.search(text)
    if dashed:
        return dashed.group(0)
    matches = _HEX32_RE.findall(text.split("?")[0])
    if matches:
        raw = matches[-1]
        return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    raise SystemExit(f"could not find a Notion page id in: {value!r}")


def _database_properties() -> dict[str, Any]:
    """The tasks schema, derived from the model so it can't drift (SPEC §2, §9)."""
    props: dict[str, Any] = {name: {"rich_text": {}} for name in CSV_COLUMNS}
    props["code"] = {"title": {}}  # a database needs exactly one title property
    props["type"] = {"select": {"options": [{"name": t.value} for t in TaskType]}}
    props["status"] = {"select": {"options": [{"name": s.value} for s in Status]}}
    props["archived"] = {"checkbox": {}}
    return props


def _raise_for_notion(response: httpx.Response) -> None:
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = (
                payload.get("message", response.text)
                if isinstance(payload, dict)
                else response.text
            )
        except ValueError:
            message = response.text
        raise SystemExit(f"Notion API error ({response.status_code}): {message}")


def _create_database(client: httpx.Client, parent_page_id: str) -> str:
    response = client.post(
        "/databases",
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": "tasks"}}],
            "properties": _database_properties(),
        },
    )
    _raise_for_notion(response)
    return str(response.json()["id"])


def _create_page(client: httpx.Client, parent_page_id: str, title: str, hint: str) -> str:
    response = client.post(
        "/pages",
        json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "properties": {"title": [{"type": "text", "text": {"content": title}}]},
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": hint}}]},
                }
            ],
        },
    )
    _raise_for_notion(response)
    return str(response.json()["id"])


def init_notion(argv: list[str], transport: httpx.BaseTransport | None = None) -> None:
    """Provision the Notion database and pages; print the ids for ``.env``."""
    args = [a for a in argv if a]
    if len(args) != 1:
        raise SystemExit(_USAGE)
    token = os.environ.get("NOTION_API_KEY")
    if not token:
        raise SystemExit(
            "Set NOTION_API_KEY in your environment or .env before running init-notion. "
            "Do NOT pass the token on the command line."
        )

    parent_page_id = _normalize_page_id(args[0])

    client = httpx.Client(
        base_url=_BASE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        },
        timeout=30.0,
        transport=transport,
    )
    with client:
        db_id = _create_database(client, parent_page_id)
        plan_id = _create_page(client, parent_page_id, "plan", _PLAN_HINT)
        context_id = _create_page(client, parent_page_id, "context", _CONTEXT_HINT)

    print("Created the Notion tasks database and plan/context pages. Add these to your .env:\n")
    print(f"NOTION_DB_ID={db_id}")
    print(f"NOTION_PLAN_PAGE_ID={plan_id}")
    print(f"NOTION_CONTEXT_PAGE_ID={context_id}")
    print("\nThen set STORAGE_BACKEND=notion. Your NOTION_API_KEY stays where it is.")
