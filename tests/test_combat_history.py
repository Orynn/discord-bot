import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from combat.engine import conclude_if_over
from combat.history import (
    archive_combat,
    finish_combat,
    format_history_detail,
    format_history_list,
    get_combat_archive,
    latest_combat_archive,
    list_combat_history,
)
from combat.storage import CombatState, CombatantState, get_combat, save_combat
from combat.text import combat_started, party_wins


class TestCombatHistory(unittest.TestCase):
    guild_id = 42
    scope_id = 7
    channel_id = 99

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        connection = getattr(db_module._thread_local, "connection", None)
        if connection is not None:
            connection.close()
            db_module._thread_local.connection = None
            db_module._thread_local.path = None
        db_module.DB_FILE = self._old_db
        self._tmpdir.cleanup()

    def _state(self, *, log: list[str] | None = None) -> CombatState:
        hero = CombatantState(
            name="Aelric",
            user_id=100,
            hp=8,
            max_hp=24,
            hand=[],
            deck=[],
        )
        goblin = CombatantState(
            name="Gobelin",
            user_id=None,
            hp=0,
            max_hp=7,
            hand=[],
            deck=[],
        )
        return CombatState(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            scope_id=self.scope_id,
            turn_order=["Aelric", "Gobelin"],
            active_index=0,
            combatants={"aelric": hero, "gobelin": goblin},
            log=log or [combat_started(), "**Gobelin** est vaincu !", party_wins()],
            map_id="tavern",
        )

    def test_finish_combat_archives_and_clears_active_state(self) -> None:
        state = self._state()
        save_combat(state)
        archive_id = finish_combat(state, winner="the party")
        self.assertIsNotNone(archive_id)
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))
        entry = get_combat_archive(
            guild_id=self.guild_id, scope_id=self.scope_id, archive_id=archive_id or 0
        )
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.winner, "the party")
        self.assertEqual(entry.map_id, "tavern")
        self.assertEqual(len(entry.log), 3)
        self.assertEqual(entry.combatants[0]["name"], "Aelric")

    def test_list_is_scoped_to_section(self) -> None:
        archive_combat(self._state(), winner="Aelric")
        archive_combat(
            CombatState(
                guild_id=self.guild_id,
                channel_id=self.channel_id,
                scope_id=99,
                turn_order=["NPC"],
                active_index=0,
                combatants={
                    "npc": CombatantState(
                        name="NPC",
                        user_id=None,
                        hp=1,
                        max_hp=1,
                        hand=[],
                        deck=[],
                    )
                },
                log=[
                    "Le combat commence — déplace-toi, puis une action (attaque ou carte)."
                ],
            ),
            winner=None,
        )
        entries = list_combat_history(guild_id=self.guild_id, scope_id=self.scope_id)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].scope_id, self.scope_id)

    def test_latest_and_detail_formatting(self) -> None:
        archive_id = archive_combat(self._state(), winner="the party")
        latest = latest_combat_archive(guild_id=self.guild_id, scope_id=self.scope_id)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.id, archive_id)
        detail = format_history_detail(latest)
        self.assertIn("Combat #", detail)
        self.assertIn("Taverne", detail)
        self.assertIn("le groupe", detail)
        self.assertIn("Aelric", detail)
        listing = format_history_list([latest])
        self.assertIn("Historique de combat", listing)
        self.assertIn(f"`#{archive_id}`", listing)

    def test_conclude_if_over_archives_winner(self) -> None:
        state = self._state()
        save_combat(state)
        result = conclude_if_over(state)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.combat_over)
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))
        latest = latest_combat_archive(guild_id=self.guild_id, scope_id=self.scope_id)
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.winner, "Aelric")

    def test_empty_list_message(self) -> None:
        self.assertIn(
            "Aucun combat archivé",
            format_history_list([]),
        )
