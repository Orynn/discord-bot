import tempfile
import unittest
from pathlib import Path

import discord
from discord import app_commands

import data.db as db_module
from bot.slash_sync import needs_sync, remember_sync


class TestSlashSync(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmp.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmp.cleanup()

    async def test_sync_only_when_commands_change(self) -> None:
        client = discord.Client(intents=discord.Intents.none())
        tree = app_commands.CommandTree(client)
        guild = discord.Object(id=42)

        @tree.command(name="ping", description="Ping", guild=guild)
        async def ping(interaction: discord.Interaction) -> None:
            pass

        self.assertTrue(needs_sync(tree, guild))
        remember_sync(tree, guild)
        self.assertFalse(needs_sync(tree, guild))
        self.assertTrue(needs_sync(tree, discord.Object(id=43)))

        @tree.command(name="pong", description="Pong", guild=guild)
        async def pong(interaction: discord.Interaction) -> None:
            pass

        self.assertTrue(needs_sync(tree, guild))


if __name__ == "__main__":
    unittest.main()
