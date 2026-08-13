"""
Discord gateway bot: registers the /dashboard slash command so users can pull
the current buy/sell ratings on demand, instead of waiting for the weekly post.

Slash-command interactions arrive over Discord's gateway (a persistent
WebSocket), unlike the plain REST posts in discord_utils.py, so this needs a
real client connection. It runs on its own asyncio event loop in a daemon
thread started from main.py, alongside the existing synchronous polling loop —
the two never share state; the command just re-reads Positions/Watchlist.csv
and the indicator CSVs fresh on each invocation, the same files the polling
loop keeps up to date.
"""
import sys
import logging
import asyncio
import threading
from pathlib import Path

import pandas as pd
import discord
from discord import app_commands

sys.path.insert(0, str(Path(__file__).parent.parent))
import Evaluation.rating_utils as rating_utils
import Notifications.discord_utils as discord_utils

logger = logging.getLogger(__name__)


class DashboardBot(discord.Client):
    def __init__(self, base_dir, channel_id):
        super().__init__(intents=discord.Intents.default())
        self.base_dir = base_dir
        self.channel_id = int(channel_id)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        guild = None
        try:
            channel = await self.fetch_channel(self.channel_id)
            guild = getattr(channel, "guild", None)
        except discord.HTTPException:
            logger.warning(
                f"Couldn't fetch DISCORD_CHANNEL_ID={self.channel_id} (check it's a channel ID, "
                "not a server ID, and that the bot has access to it) — syncing /dashboard globally instead"
            )

        if guild is not None:
            # guild-scoped sync propagates instantly; global sync can take up to an hour
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Synced /dashboard command to guild {guild.id}")
        else:
            await self.tree.sync()
            logger.info("Synced /dashboard command globally")

    async def on_ready(self):
        logger.info(f"Discord bot logged in as {self.user} (id={self.user.id})")


def _watchlist_tickers(base_dir):
    return pd.read_csv(Path(base_dir) / "Positions/Watchlist.csv")["Ticker"]


def _build_bot(base_dir, channel_id):
    bot = DashboardBot(base_dir, channel_id)

    @bot.tree.command(name="dashboard", description="Show the current buy/sell rating for every tracked position")
    async def dashboard(interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            ratings = rating_utils.all_ratings(_watchlist_tickers(bot.base_dir), bot.base_dir)
            message = discord_utils.format_ratings_table(ratings, "Buy/Sell Ratings")
        except Exception:
            logger.exception("Failed to build /dashboard response")
            await interaction.followup.send("Failed to load ratings — check the logs.")
            return

        for chunk in discord_utils.chunk_message(message):
            await interaction.followup.send(chunk)

    return bot


def run_in_background(base_dir, token, channel_id):
    """Starts the gateway bot on its own event loop in a daemon thread. Returns immediately."""
    def _runner():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = _build_bot(base_dir, channel_id)
        try:
            loop.run_until_complete(bot.start(token))
        except Exception:
            logger.exception("Discord slash-command bot crashed")

    thread = threading.Thread(target=_runner, name="discord-bot", daemon=True)
    thread.start()
    return thread
