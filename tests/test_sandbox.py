import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import data.db as db_module
from combat.storage import CombatState, CombatantState, get_combat, save_combat
from initiative.storage import InitiativeEntry, InitiativeState, get_initiative, save_initiative
from players.discover import sandbox_player_id
from sheets.sandbox import MOCK_NAME, build_mock_sheet, ensure_sandbox_sheet, reset_sandbox
from sheets.storage import get_sheet, save_sheet
from sheets.data import CharacterSheet


class TestSandboxMock(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_mock_sheet_is_ready_to_fight(self) -> None:
        sheet = build_mock_sheet()
        self.assertEqual(sheet.name, MOCK_NAME)
        self.assertEqual(sheet.hp_current, sheet.hp_max)
        self.assertGreater(sheet.hp_max, 0)
        self.assertIn("fire-bolt", sheet.spells)
        self.assertIn("cure-wounds", sheet.spells)
        self.assertTrue(sheet.spell_slots.has_slots())
        self.assertTrue(any(item.kind == "weapon" for item in sheet.equipment.items))

    def test_ensure_does_not_overwrite_existing_mock(self) -> None:
        save_sheet(
            user_id=-404,
            guild_id=7,
            sheet=CharacterSheet(name="Edited", hp_current=3, hp_max=10),
        )
        sheet = ensure_sandbox_sheet(guild_id=7, user_id=-404)
        self.assertEqual(sheet.name, "Edited")
        self.assertEqual(sheet.hp_current, 3)

    def test_reset_reseeds_sheet_and_clears_fight(self) -> None:
        trash = MagicMock()
        trash.id = 404
        trash.name = "🚯trash"
        self.assertEqual(sandbox_player_id(trash), -404)
        save_sheet(
            user_id=-404,
            guild_id=7,
            sheet=CharacterSheet(name="Broken", hp_current=0, hp_max=10),
        )
        save_combat(
            CombatState(
                guild_id=7,
                channel_id=404,
                turn_order=["Mock"],
                active_index=0,
                scope_id=404,
                combatants={
                    "mock": CombatantState(
                        name="Mock",
                        user_id=-404,
                        hp=0,
                        max_hp=10,
                        hand=[],
                        deck=[],
                    )
                },
            )
        )
        save_initiative(
            guild_id=7,
            scope_id=404,
            state=InitiativeState(
                channel_id=404,
                active_index=0,
                order=[InitiativeEntry(name="Mock", total=10, user_id=-404)],
            ),
        )
        sheet = reset_sandbox(guild_id=7, channel=trash)
        self.assertEqual(sheet.name, MOCK_NAME)
        self.assertEqual(sheet.hp_current, 44)
        loaded = get_sheet(user_id=-404, guild_id=7)
        assert loaded is not None
        self.assertEqual(loaded.hp_current, 44)
        self.assertIsNone(get_combat(guild_id=7, scope_id=404))
        self.assertIsNone(get_initiative(guild_id=7, scope_id=404))
        real = get_sheet(user_id=1, guild_id=7)
        self.assertIsNone(real)
