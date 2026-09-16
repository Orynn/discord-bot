import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import data.db as db_module
from players.scope import scope_id_for_channel
from players.storage import save_player_section


class TestPlayerScope(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_scope_id_comes_from_player_channel(self) -> None:
        save_player_section(
            guild_id=7,
            user_id=42,
            data={
                "name": "Fox",
                "category_id": 10,
                "ooc_channel_id": 20,
                "roleplay_channel_id": 21,
            },
        )
        guild = MagicMock()
        guild.id = 7
        ooc = MagicMock()
        ooc.id = 20
        ooc.category_id = 10
        ooc.category = MagicMock(id=10)
        ooc.name = "blabla"
        self.assertEqual(scope_id_for_channel(guild=guild, channel=ooc), 42)
        elsewhere = MagicMock()
        elsewhere.id = 99
        elsewhere.category_id = 88
        elsewhere.name = "general"
        elsewhere_category = MagicMock()
        elsewhere_category.id = 88
        elsewhere_category.name = "general"
        elsewhere_category.channels = []
        elsewhere.category = elsewhere_category
        self.assertIsNone(scope_id_for_channel(guild=guild, channel=elsewhere))

    def test_scope_id_uses_trash_channel_as_sandbox(self) -> None:
        guild = MagicMock()
        guild.id = 7
        trash = MagicMock()
        trash.id = 404
        trash.name = "🚯trash"
        trash.category_id = 88
        trash.category = MagicMock(id=88, name="staff", channels=[])
        self.assertEqual(scope_id_for_channel(guild=guild, channel=trash), 404)
