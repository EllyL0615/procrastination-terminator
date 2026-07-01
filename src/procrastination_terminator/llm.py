"""LLM client wrapper (SPEC §9).

The LLM does all the judgement work: classifying task type, judging whether a
reply is genuine, condensing progress to one line, matching a fuzzy code to a
task, and writing the message tone (personality x intensity). Targets any
OpenAI-compatible chat endpoint via httpx (DeepSeek, a Claude-compatible
gateway, etc.); the endpoint, model, and message language come from config.
"""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from .config import Config
from .models import Personality, Task, TaskType

# Outcome of classifying an in-progress task's reply (SPEC §4.2, §6).
ReplyKind = Literal["completed", "progress", "chat"]

_PERSONA: dict[Personality, str] = {
    Personality.GENTLE: "gentle and encouraging",
    Personality.STRICT: "strict and pressuring",
    Personality.SARCASTIC: "passive-aggressive and sarcastic",
}
_LANGUAGE_NAME: dict[str, str] = {"zh": "Chinese", "en": "English"}


def _extract_json(content: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating ```json fences."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[len("json") :]
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


class LLMClient:
    """Thin async wrapper over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=30.0,
        )

    async def _chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)  # recent conversation turns, oldest first
        messages.append({"role": "user", "content": user})
        payload: dict[str, Any] = {"model": self._config.llm_model, "messages": messages}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = await self._http.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])

    async def classify_type(self, description: str) -> TaskType:
        """Classify a task description into a TaskType (SPEC §2)."""
        content = await self._chat(
            "Classify the task into one of: study, work, outing, other. "
            'Reply as JSON: {"type": "<value>"}.',
            description,
            json_mode=True,
        )
        return TaskType(_extract_json(content)["type"])

    async def judge_started(self, task: Task, reply: str) -> bool:
        """Judge, with a high bar, whether the reply shows the user really started (SPEC §4.1)."""
        return await self._judge_bool(
            f"The user was nagged to start the task: {task.description!r}. "
            "Answer yes only if the message clearly shows they have actually begun focusing "
            "on it -- not merely acknowledging, agreeing, or saying they will soon. If in "
            'doubt, answer no. Reply as JSON: {"yes": true|false}.',
            reply,
        )

    async def classify_progress_reply(self, task: Task, reply: str) -> ReplyKind:
        """Classify an in-progress task's reply in one call (SPEC §4.2, §6).

        ``"completed"`` = the task is finished; ``"progress"`` = SUBSTANTIVE new info
        about the task (what is done, how far along, a specific blocker) worth
        recording; ``"chat"`` = everything else, including bare acknowledgements,
        promises, or intentions ("I'll focus") that carry no concrete progress -- so a
        vague reply never overwrites a real one. Unknown output falls back to ``"chat"``
        (safe: leaves the file untouched).
        """
        content = await self._chat(
            f"The user is working on the task: {task.description!r}. Classify their message.\n"
            '- "completed": it clearly means the task is finished.\n'
            '- "progress": it reports substantive new information about how the task itself '
            "is going -- what they have done, how far along they are, or a specific obstacle. "
            "It must carry real content worth recording.\n"
            '- "chat": everything else -- acknowledgements, promises, or intentions to work '
            '("ok", "I will focus now", "I will do it properly"), reactions to you, mood, '
            "small talk, or off-topic. A vague promise with no concrete task detail is chat, "
            "NOT progress.\n"
            'Reply as JSON: {"kind": "completed" | "progress" | "chat"}.',
            reply,
            json_mode=True,
        )
        kind = str(_extract_json(content).get("kind", "")).lower()
        if kind == "completed":
            return "completed"
        if kind == "progress":
            return "progress"
        return "chat"

    async def _judge_bool(self, system: str, reply: str) -> bool:
        content = await self._chat(system, reply, json_mode=True)
        return bool(_extract_json(content)["yes"])

    async def condense_progress(self, reply: str) -> str:
        """Condense a progress reply into one short line (SPEC §4.2)."""
        return (
            await self._chat(
                "Condense the user's progress update into one short line. "
                "Output only that line, no quotes.",
                reply,
            )
        ).strip()

    async def match_code(self, tasks: list[Task], fuzzy: str) -> Task | None:
        """Match a fuzzy code to a task; None if ambiguous or no match (SPEC §6, §4.4)."""
        if not tasks:
            return None
        catalogue = "\n".join(f"{t.code}: {t.description}" for t in tasks)
        content = await self._chat(
            "Pick which task the user means. Tasks (code: description):\n"
            f"{catalogue}\n"
            'Reply as JSON: {"code": "<code>"} or {"code": null} if unclear or ambiguous.',
            fuzzy,
            json_mode=True,
        )
        code = _extract_json(content).get("code")
        return next((t for t in tasks if t.code == code), None)

    async def generate_message(
        self,
        situation: str,
        *,
        personality: Personality,
        intensity: int = 0,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Write one styled message for ``situation`` (SPEC §4.5).

        ``situation`` describes what to say (built by the bot); this applies the
        persona, escalation ``intensity`` (0 = mild), and the configured language.
        ``history`` is the recent channel conversation (oldest first); it grounds the
        wording so an in-chat correction the user just made is honored (SPEC §4.5).
        """
        language = _LANGUAGE_NAME.get(self._config.message_language, self._config.message_language)
        system = (
            f"You are {self._config.bot_name}, a study accountability bot nudging one user. "
            f"Write a single short message in {language}. "
            f"Persona: {_PERSONA[personality]}. "
            f"Forcefulness: {intensity} (0 = mild, higher = more intense). "
            "The turns before this are your recent chat history with the user; honor any "
            "correction or clarification they made there (e.g. what a task really is). "
            "Output only the message text."
        )
        return (await self._chat(system, situation, history=history)).strip()

    async def parse_plan(self, text: str) -> list[dict[str, str]]:
        """Extract structured task entries from free-form plan.txt (SPEC §9).

        Each entry has date (MM.DD), time (HH:MM start), subject (short tag),
        description, and type; :func:`plan_parser.build_tasks` assembles them.
        """
        content = await self._chat(
            "Extract the user's tasks from their plan. For each task output: "
            "date (MM.DD), time (HH:MM start), subject (a short uppercase tag like PGM), "
            "description, and type (one of study, work, outing, other). "
            'Reply as JSON: {"tasks": [{"date": ..., "time": ..., "subject": ..., '
            '"description": ..., "type": ...}, ...]}.',
            text,
            json_mode=True,
        )
        raw = _extract_json(content).get("tasks", [])
        return [{str(k): str(v) for k, v in item.items()} for item in raw]

    async def plan_edits(self, tasks: list[Task], instruction: str) -> list[dict[str, str]]:
        """Turn a natural-language edit into structured operations on the table (SPEC §6)."""
        catalogue = "\n".join(
            f"{t.code} | {t.planned_start}-{t.planned_end} | {t.type.value} | "
            f"{t.status.value} | {t.description}"
            for t in tasks
        )
        content = await self._chat(
            "Apply the user's edit to their task table (code | time | type | status | "
            f"description):\n{catalogue}\n"
            'Reply as JSON: {"edits": [{"op": "delete", "code": "..."} or '
            '{"op": "update", "code": "...", and any of planned_start, planned_end, '
            "description, type, status to change}]}.",
            instruction,
            json_mode=True,
        )
        raw = _extract_json(content).get("edits", [])
        return [{str(k): str(v) for k, v in item.items()} for item in raw]

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
