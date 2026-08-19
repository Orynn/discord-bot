import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from sheets.data import CharacterSheet
from sheets.storage import get_sheet, save_sheet, update_sheet


class TestSpellSlugMigration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_save_sheet_normalizes_legacy_slugs(self) -> None:
        save_sheet(
            user_id=1,
            sheet=CharacterSheet(name="Mage", spells=["srd-2024_fireball", "wotc-srd_shield"]),
        )
        loaded = get_sheet(user_id=1)
        assert loaded is not None
        self.assertEqual(loaded.spells, ["fireball", "shield"])

    def test_update_sheet_persists_migrated_slugs(self) -> None:
        with db_module.db_connection() as connection:
            connection.execute(
                "INSERT INTO sheets (user_id, data) VALUES (?, ?)",
                (
                    "1",
                    '{"name": "Mage", "spells": ["srd-2024_fireball"]}',
                ),
            )

        def _touch(sheet: CharacterSheet) -> None:
            sheet.notes = "updated"

        update_sheet(user_id=1, updater=_touch)
        loaded = get_sheet(user_id=1)
        assert loaded is not None
        self.assertEqual(loaded.spells, ["fireball"])
        self.assertEqual(loaded.notes, "updated")


if __name__ == "__main__":
    unittest.main()
