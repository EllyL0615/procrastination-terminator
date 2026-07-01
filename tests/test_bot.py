"""Behavioural tests for the ``!clear`` channel-cleanup command (SPEC §6).

``bot.py`` is integration code (SPEC §9), but ``_clear`` has enough branching --
arg parsing, per-author selection, count vs. duration -- to be worth pinning. We
drive the real coroutine against a tiny fake Discord channel, so no live Discord
or secrets are needed; only the selection/deletion logic is exercised.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from types import SimpleNamespace
from typing import cast
from zoneinfo import ZoneInfo

import discord
import pytest

from procrastination_terminator.bot import Supervisor

BOT_ID = 1
USER_ID = 2
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _Author:
    id: int


@dataclass
class _Msg:
    author: _Author
    created_at: datetime
    content: str = ""
    deleted: bool = False

    async def delete(self) -> None:
        self.deleted = True


class _Channel:
    """Fake channel: ``history`` streams newest-first, honouring ``after``."""

    def __init__(self, messages: list[_Msg]) -> None:
        self._messages = messages  # newest first, as Discord returns them
        self.sent: list[str] = []

    def history(
        self, *, limit: int | None = None, after: datetime | None = None
    ) -> AsyncIterator[_Msg]:
        messages = self._messages if limit is None else self._messages[:limit]

        async def _gen() -> AsyncIterator[_Msg]:
            for message in messages:
                if after is not None and message.created_at <= after:
                    continue
                yield message

        return _gen()

    async def send(self, text: str) -> None:
        self.sent.append(text)


@dataclass
class _Cfg:
    tz: tzinfo
    discord_user_id: int = USER_ID
    dialogue_history_limit: int = 12


class _Bot:
    """Just the surface ``_clear`` / ``_recent_dialogue`` touch on ``Supervisor``."""

    def __init__(self, messages: list[_Msg], *, tz: tzinfo = UTC) -> None:
        self.user = _Author(BOT_ID)
        self.config = _Cfg(tz=tz)
        self.chan = _Channel(messages)

    async def _channel(self) -> _Channel:
        return self.chan

    async def _send(self, text: str, *, mention: bool = False) -> None:
        self.chan.sent.append(text)


def _bot_msg(minutes_ago: int = 0) -> _Msg:
    return _Msg(_Author(BOT_ID), _EPOCH - timedelta(minutes=minutes_ago))


def _user_msg(minutes_ago: int = 0) -> _Msg:
    return _Msg(_Author(USER_ID), _EPOCH - timedelta(minutes=minutes_ago))


def _run(bot: _Bot, arg: str) -> None:
    asyncio.run(Supervisor._clear(cast(Supervisor, bot), arg))


def test_clear_bare_deletes_only_the_newest_bot_message() -> None:
    messages = [_bot_msg(), _user_msg(), _bot_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "")

    assert [m.deleted for m in messages] == [True, False, False, False]
    assert bot.chan.sent[-1] == "Deleted 1 of my own message(s)."


def test_clear_count_takes_newest_n_bot_messages_skipping_user_messages() -> None:
    # newest -> oldest: bot, user, bot, bot, user, bot  (4 bot messages)
    messages = [_bot_msg(), _user_msg(), _bot_msg(), _bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "3")

    assert [m.deleted for m in messages] == [True, False, True, True, False, False]
    assert bot.chan.sent[-1] == "Deleted 3 of my own message(s)."


def test_clear_count_exceeding_available_deletes_what_exists() -> None:
    messages = [_bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "10")

    assert [m.deleted for m in messages] == [True, False, True]
    assert bot.chan.sent[-1] == "Deleted 2 of my own message(s)."


def test_clear_all_deletes_every_bot_message_and_no_user_message() -> None:
    messages = [_bot_msg(), _user_msg(), _bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "all")

    assert [m.deleted for m in messages] == [True, False, True, False, True]
    assert bot.chan.sent[-1] == "Deleted 3 of my own message(s)."


def test_clear_duration_deletes_only_bot_messages_inside_the_window() -> None:
    # Timestamps relative to *now*, since _clear computes cutoff from now.
    now = datetime.now(UTC)
    recent_bot = _Msg(_Author(BOT_ID), now - timedelta(minutes=10))
    recent_user = _Msg(_Author(USER_ID), now - timedelta(minutes=20))
    old_bot = _Msg(_Author(BOT_ID), now - timedelta(minutes=90))
    bot = _Bot([recent_bot, recent_user, old_bot])

    _run(bot, "60m")

    assert recent_bot.deleted is True
    assert recent_user.deleted is False
    assert old_bot.deleted is False
    assert bot.chan.sent[-1] == "Deleted 1 of my own message(s)."


def test_clear_zero_count_reports_usage_and_deletes_nothing() -> None:
    messages = [_bot_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "0")

    assert not any(m.deleted for m in messages)
    assert bot.chan.sent == ["!clear <N> needs a positive count."]


def test_clear_invalid_arg_reports_usage_and_deletes_nothing() -> None:
    messages = [_bot_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "xyz")

    assert not any(m.deleted for m in messages)
    assert len(bot.chan.sent) == 1
    assert bot.chan.sent[0].startswith("Usage:")


# -- _recent_dialogue -------------------------------------------------------------
# The dialogue history only grounds the LLM's *wording*; its ``[MM-DD HH:MM]`` stamps
# never reach the monitor, whose timing stays snapshot+clock based (memoryless,
# SPEC §3.2). These tests pin the stamp format, tz conversion, ordering and filtering.

_LONDON = ZoneInfo("Europe/London")  # UTC+1 (BST) in July, UTC+0 in January


def _dialogue_msg(author_id: int, at: datetime, content: str) -> _Msg:
    return _Msg(_Author(author_id), at, content)


def _dialogue(bot: _Bot) -> list[dict[str, str]]:
    return asyncio.run(Supervisor._recent_dialogue(cast(Supervisor, bot)))


def test_recent_dialogue_stamps_time_in_config_tz_oldest_first() -> None:
    # Discord returns newest-first; created_at is UTC. In July, London is BST (UTC+1),
    # so 13:00/13:30 UTC read as 14:00/14:30 local.
    messages = [
        _dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "did the reading"),
        _dialogue_msg(BOT_ID, datetime(2026, 7, 1, 13, 0, tzinfo=UTC), "how's it going?"),
    ]
    bot = _Bot(messages, tz=_LONDON)

    assert _dialogue(bot) == [
        {"role": "assistant", "content": "[07-01 14:00] how's it going?"},
        {"role": "user", "content": "[07-01 14:30] did the reading"},
    ]


def test_recent_dialogue_stamps_utc_when_config_tz_is_utc() -> None:
    messages = [_dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "done")]
    bot = _Bot(messages, tz=UTC)

    assert _dialogue(bot) == [{"role": "user", "content": "[07-01 13:30] done"}]


def test_recent_dialogue_strips_content_and_skips_blank_turns() -> None:
    messages = [
        _dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 30, tzinfo=UTC), "   "),
        _dialogue_msg(BOT_ID, datetime(2026, 7, 1, 13, 0, tzinfo=UTC), "  keep at it  "),
    ]
    bot = _Bot(messages, tz=UTC)

    assert _dialogue(bot) == [{"role": "assistant", "content": "[07-01 13:00] keep at it"}]


# -- error containment ------------------------------------------------------------
# An exception escaping the ext.tasks loop terminates it for good (bot online, never
# nagging again), and an exception in on_message is only a server-side traceback.
# These pin the guards: a failed tick is skipped and retried, a failed command tells
# the user, and a failed day boundary is re-attempted next tick instead of being
# marked done for the day.


def test_tick_swallows_a_failing_supervise_pass() -> None:
    class _Boom:
        config = SimpleNamespace(tz=UTC)

        async def _maybe_boundaries(self, now: datetime) -> None:
            raise RuntimeError("LLM down")

        async def _supervise(self, now: datetime) -> None:
            raise AssertionError("unreachable: boundaries already raised")

    asyncio.run(Supervisor.tick.coro(cast(Supervisor, _Boom())))  # must not raise


def test_on_message_failure_is_reported_to_the_user() -> None:
    @dataclass
    class _Failing:
        config = SimpleNamespace(discord_user_id=USER_ID, discord_channel_id=7)
        sent: list[str] = field(default_factory=list)

        async def _command(self, name: str, arg: str) -> None:
            raise RuntimeError("LLM down")

        async def _send(self, text: str, *, mention: bool = False) -> None:
            self.sent.append(text)

    bot = _Failing()
    message = SimpleNamespace(
        author=_Author(USER_ID), channel=SimpleNamespace(id=7), content="!sync"
    )
    asyncio.run(Supervisor.on_message(cast(Supervisor, bot), cast(discord.Message, message)))
    assert bot.sent == ["Something went wrong handling that; please try again."]


def test_failed_day_start_boundary_retries_next_tick() -> None:
    class _Flaky:
        config = SimpleNamespace(day_start=time(4, 0), day_end=time(23, 0))
        _last_day_start: date | None = None
        _last_day_end: date | None = None
        calls = 0

        async def _day_start(self, now: datetime) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")

        async def _day_end(self, now: datetime) -> None:
            raise AssertionError("day end must not fire at 04:30")

    bot = _Flaky()
    now = datetime(2026, 7, 1, 4, 30, tzinfo=UTC)
    with pytest.raises(RuntimeError):  # first attempt fails (the tick loop catches it)
        asyncio.run(Supervisor._maybe_boundaries(cast(Supervisor, bot), now))
    assert bot._last_day_start is None  # not marked done, so the next tick retries

    asyncio.run(Supervisor._maybe_boundaries(cast(Supervisor, bot), now))
    assert bot.calls == 2
    assert bot._last_day_start == date(2026, 7, 1)  # only marked done on success

    asyncio.run(Supervisor._maybe_boundaries(cast(Supervisor, bot), now))
    assert bot.calls == 2  # done for the day; no third firing


def test_recent_dialogue_honors_history_limit() -> None:
    # newest-first; only the newest ``dialogue_history_limit`` turns are fetched.
    messages = [
        _dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 20, tzinfo=UTC), "third"),
        _dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 10, tzinfo=UTC), "second"),
        _dialogue_msg(USER_ID, datetime(2026, 7, 1, 13, 0, tzinfo=UTC), "first"),
    ]
    bot = _Bot(messages, tz=UTC)
    bot.config.dialogue_history_limit = 2

    assert _dialogue(bot) == [
        {"role": "user", "content": "[07-01 13:10] second"},
        {"role": "user", "content": "[07-01 13:20] third"},
    ]
