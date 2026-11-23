import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.events import register_events


class TestOnReady(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_only_reruns_catch_up(self) -> None:
        bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
        register_events(bot)
        with (
            patch(
                "bot.events.catch_up_missed_commands", new_callable=AsyncMock
            ) as catch_up,
            patch("bot.events.register_persistent_views") as views,
            patch("bot.events.reset_session_tracking") as reset,
            patch("bot.events.is_available", return_value=False),
            patch.object(type(bot), "guilds", new=[]),
            patch.object(type(bot), "user", new=MagicMock()),
        ):
            await bot.on_ready()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            await bot.on_ready()
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        views.assert_called_once()
        reset.assert_called_once()
        self.assertEqual(catch_up.await_count, 2)


if __name__ == "__main__":
    unittest.main()
