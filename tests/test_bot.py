"""Behavioural tests for the ``!clear`` DM-cleanup command (SPEC §6).

``bot.py`` is integration code (SPEC §9), but ``_clear`` has enough branching --
arg parsing, per-author selection, count vs. duration -- to be worth pinning. We
drive the real coroutine against a tiny fake Discord channel, so no live Discord
or secrets are needed; only the selection/deletion logic is exercised.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast

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
    deleted: bool = False

    async def delete(self) -> None:
        self.deleted = True


class _Channel:
    """Fake DM channel: ``history`` streams newest-first, honouring ``after``."""

    def __init__(self, messages: list[_Msg]) -> None:
        self._messages = messages  # newest first, as Discord returns them
        self.sent: list[str] = []

    def history(
        self, *, limit: int | None = None, after: datetime | None = None
    ) -> AsyncIterator[_Msg]:
        messages = self._messages

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


class _Bot:
    """Just the surface ``_clear`` touches on ``Supervisor``."""

    def __init__(self, messages: list[_Msg]) -> None:
        self.user = _Author(BOT_ID)
        self.config = _Cfg(tz=UTC)
        self._channel = _Channel(messages)

    async def _dm_channel(self) -> _Channel:
        return self._channel

    async def _dm(self, text: str) -> None:
        self._channel.sent.append(text)


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
    assert bot._channel.sent[-1] == "Deleted 1 of my own message(s)."


def test_clear_count_takes_newest_n_bot_messages_skipping_user_messages() -> None:
    # newest -> oldest: bot, user, bot, bot, user, bot  (4 bot messages)
    messages = [_bot_msg(), _user_msg(), _bot_msg(), _bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "3")

    assert [m.deleted for m in messages] == [True, False, True, True, False, False]
    assert bot._channel.sent[-1] == "Deleted 3 of my own message(s)."


def test_clear_count_exceeding_available_deletes_what_exists() -> None:
    messages = [_bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "10")

    assert [m.deleted for m in messages] == [True, False, True]
    assert bot._channel.sent[-1] == "Deleted 2 of my own message(s)."


def test_clear_all_deletes_every_bot_message_and_no_user_message() -> None:
    messages = [_bot_msg(), _user_msg(), _bot_msg(), _user_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "all")

    assert [m.deleted for m in messages] == [True, False, True, False, True]
    assert bot._channel.sent[-1] == "Deleted 3 of my own message(s)."


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
    assert bot._channel.sent[-1] == "Deleted 1 of my own message(s)."


def test_clear_zero_count_reports_usage_and_deletes_nothing() -> None:
    messages = [_bot_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "0")

    assert not any(m.deleted for m in messages)
    assert bot._channel.sent == ["!clear <N> needs a positive count."]


def test_clear_invalid_arg_reports_usage_and_deletes_nothing() -> None:
    messages = [_bot_msg(), _bot_msg()]
    bot = _Bot(messages)

    _run(bot, "xyz")

    assert not any(m.deleted for m in messages)
    assert len(bot._channel.sent) == 1
    assert bot._channel.sent[0].startswith("Usage:")
