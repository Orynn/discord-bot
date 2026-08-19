import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import data.db as db_module
from players.setup import build_welcome_embed, ensure_player_sheet
from players.storage import (
    delete_player_section,
    get_player_section,
    list_player_sections,
    save_player_section,
)
from sheets.storage import get_character_name, get_sheet


class TestPlayerStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_list_and_delete(self) -> None:
        save_player_section(
            guild_id=1,
            user_id=42,
            data={"name": "LEO", "category_id": 100},
        )
        save_player_section(
            guild_id=1,
            user_id=99,
            data={"name": "BOB", "category_id": 101},
        )

        entries = list_player_sections(guild_id=1)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][1]["name"], "BOB")

        removed = delete_player_section(guild_id=1, user_id=42)
        assert removed is not None
        self.assertEqual(removed["name"], "LEO")
        self.assertIsNone(get_player_section(guild_id=1, user_id=42))
        self.assertEqual(len(list_player_sections(guild_id=1)), 1)


class TestEnsurePlayerSheet(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_creates_sheet_and_pcname(self) -> None:
        sheet, created = ensure_player_sheet(user_id=7, name="Magnus")
        self.assertTrue(created)
        self.assertEqual(sheet.name, "Magnus")
        self.assertEqual(get_character_name(user_id=7), "Magnus")
        self.assertIsNotNone(get_sheet(user_id=7))

    def test_updates_existing_sheet_name(self) -> None:
        ensure_player_sheet(user_id=7, name="Old Name")
        _, created = ensure_player_sheet(user_id=7, name="New Name")
        self.assertFalse(created)
        self.assertEqual(get_sheet(user_id=7).name, "New Name")
        self.assertEqual(get_character_name(user_id=7), "New Name")


class TestWelcomeEmbed(unittest.TestCase):
    def test_includes_character_name(self) -> None:
        member = MagicMock()
        member.mention = "@Player"
        embed = build_welcome_embed(character_name="Leo", member=member)
        self.assertIn("Leo", embed.title)
        text = (embed.description or "") + "".join(field.value for field in embed.fields)
        self.assertIn(";sheet show", text)


if __name__ == "__main__":
    unittest.main()
