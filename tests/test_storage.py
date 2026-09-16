import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from sheets.currency import Currency
from sheets.data import CharacterSheet
from sheets.storage import get_sheet, save_sheet, transfer_currency, update_sheet


class TestTransferCurrency(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

        payer = CharacterSheet(name="Payer", currency=Currency(gp=100))
        recipient = CharacterSheet(name="Recipient", currency=Currency(gp=10))
        save_sheet(user_id=1, guild_id=1, sheet=payer)
        save_sheet(user_id=2, guild_id=1, sheet=recipient)

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_transfers_funds_atomically(self) -> None:
        transfer_currency(
            guild_id=1, payer_id=1, recipient_id=2, payment=Currency(gp=25)
        )

        payer = get_sheet(user_id=1, guild_id=1)
        recipient = get_sheet(user_id=2, guild_id=1)
        assert payer is not None and recipient is not None
        self.assertEqual(payer.currency.total_cp(), 7500)
        self.assertEqual(recipient.currency.total_cp(), 3500)

    def test_rejects_insufficient_funds(self) -> None:
        with self.assertRaises(ValueError):
            transfer_currency(
                guild_id=1, payer_id=1, recipient_id=2, payment=Currency(gp=500)
            )

        payer = get_sheet(user_id=1, guild_id=1)
        recipient = get_sheet(user_id=2, guild_id=1)
        assert payer is not None and recipient is not None
        self.assertEqual(payer.currency.total_cp(), 10000)
        self.assertEqual(recipient.currency.total_cp(), 1000)


class TestUpdateSheet(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        save_sheet(
            user_id=1,
            guild_id=1,
            sheet=CharacterSheet(name="Hero", hp_current=10, hp_max=20),
        )

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_updates_in_single_transaction(self) -> None:
        def _heal(sheet: CharacterSheet) -> None:
            sheet.hp_current = 20

        updated = update_sheet(user_id=1, guild_id=1, updater=_heal)
        self.assertEqual(updated.hp_current, 20)
        loaded = get_sheet(user_id=1, guild_id=1)
        assert loaded is not None
        self.assertEqual(loaded.hp_current, 20)

    def test_sheets_are_isolated_by_guild(self) -> None:
        save_sheet(user_id=1, guild_id=1, sheet=CharacterSheet(name="Home Hero"))
        save_sheet(user_id=1, guild_id=2, sheet=CharacterSheet(name="Other Hero"))
        home = get_sheet(user_id=1, guild_id=1)
        other = get_sheet(user_id=1, guild_id=2)
        assert home is not None and other is not None
        self.assertEqual(home.name, "Home Hero")
        self.assertEqual(other.name, "Other Hero")


class TestRetiredCombatTables(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_init_db_drops_legacy_combat_tables(self) -> None:
        db_module.init_db()
        with db_module.db_connection() as connection:
            connection.executescript(
                """
                CREATE TABLE combat (guild_id TEXT, scope_id TEXT, state_json TEXT);
                CREATE TABLE combat_maps (guild_id TEXT, map_id TEXT);
                CREATE TABLE combat_history (id INTEGER);
                """
            )
        db_module.init_db()
        with db_module.db_connection() as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertNotIn("combat", names)
        self.assertNotIn("combat_maps", names)
        self.assertNotIn("combat_history", names)
        self.assertIn("initiative", names)


if __name__ == "__main__":
    unittest.main()
