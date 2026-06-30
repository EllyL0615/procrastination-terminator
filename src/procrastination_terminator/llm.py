"""LLM client wrapper (SPEC §9).

The LLM does all the judgement work: parsing plan.txt, classifying task type,
judging whether a reply is genuine, condensing progress to one line, generating
the message tone (personality x intensity), and matching a fuzzy code to a task.
Targets any OpenAI-compatible chat endpoint via httpx (DeepSeek, a Claude-
compatible gateway, etc.); the endpoint and model come from config.
"""

from __future__ import annotations

import httpx

from .config import Config
from .models import Task, TaskType


class LLMClient:
    """Thin async wrapper over an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._http = httpx.AsyncClient(
            base_url=config.llm_base_url,
            headers={"Authorization": f"Bearer {config.llm_api_key}"},
            timeout=30.0,
        )

    async def classify_type(self, description: str) -> TaskType:
        """Classify a task description into a TaskType (SPEC §2)."""
        raise NotImplementedError

    async def judge_started(self, task: Task, reply: str) -> bool:
        """Judge whether the user's reply means they actually started (SPEC §4.1)."""
        raise NotImplementedError

    async def judge_completed(self, task: Task, reply: str) -> bool:
        """Judge whether the user's reply means the task is done (SPEC §4.2)."""
        raise NotImplementedError

    async def condense_progress(self, reply: str) -> str:
        """Condense a progress reply into one short line (SPEC §4.2)."""
        raise NotImplementedError

    async def match_code(self, tasks: list[Task], fuzzy: str) -> Task | None:
        """Match a fuzzy code to a task; None if ambiguous (SPEC §6, §4.4)."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()
