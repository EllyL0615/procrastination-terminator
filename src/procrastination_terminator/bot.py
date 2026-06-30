"""Discord wiring (SPEC §9).

discord.py carries everything: DM send/receive, the per-minute supervisor poll
(``ext.tasks`` ``@tasks.loop(minutes=1)``), and the day-start / day-end triggers
(checked by time inside the loop, so no APScheduler). Command handlers for
``!已开始`` / ``!已完成`` / ``!重载`` / ``!进度`` / ``!修改`` and free-chat are
registered during implementation; see SPEC §3 and §6.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from .config import Config


def build_bot(config: Config) -> commands.Bot:
    """Construct the Discord bot. Loop and command registration come later."""
    intents = discord.Intents.default()
    intents.message_content = True
    return commands.Bot(command_prefix="!", intents=intents)


def run(config: Config) -> None:
    """Build and run the bot until disconnected."""
    build_bot(config).run(config.discord_token)
