import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import data.db as db_module
from combat.cards import DODGE_CARD_ID, HAND_SIZE, WEAPON_CARD_ID, spell_card_id
from combat.engine import end_turn, play_card, start_combat
from combat.storage import CombatState, CombatantState, clear_combat, get_combat, save_combat
from initiative.storage import InitiativeEntry, InitiativeState, save_initiative
from sheets.data import CharacterSheet
from sheets.spell_slots import SpellSlots
from sheets.storage import get_sheet, save_sheet


def _mock_spell(slug: str, *, level: int = 0, damage_roll: str = "1d8", healing: bool = False) -> dict:
    return {
        "key": f"srd-2024_{slug}",
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "level": level,
        "school": "Evocation",
        "desc": "Regain hit points." if healing else "Deal damage.",
        "damage_roll": damage_roll,
        "damage_types": [] if healing else ["force"],
    }


class TestCombatEngine(unittest.IsolatedAsyncioTestCase):
    guild_id = 42
    channel_id = 99

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        clear_combat(guild_id=self.guild_id)

        save_initiative(
            guild_id=self.guild_id,
            state=InitiativeState(
                channel_id=self.channel_id,
                active_index=0,
                order=[
                    InitiativeEntry(name="Hero", total=18, user_id=1),
                    InitiativeEntry(name="Goblin", total=12, user_id=None),
                ],
            ),
        )
        save_sheet(
            user_id=1,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Fighter",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={"str": 16, "dex": 12, "con": 14, "int": 10, "wis": 10, "cha": 10},
                spells=["fire-bolt"],
            ),
        )

    async def asyncTearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_start_combat_builds_sheet_deck(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")

        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]

        self.assertIn(WEAPON_CARD_ID, hero.card_catalog)
        self.assertIn(DODGE_CARD_ID, hero.card_catalog)
        self.assertIn(spell_card_id("fire-bolt"), hero.card_catalog)
        self.assertEqual(len(hero.hand), HAND_SIZE)
        self.assertIn(WEAPON_CARD_ID, goblin.card_catalog)
        self.assertNotIn(spell_card_id("fire-bolt"), goblin.card_catalog)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_weapon_attack_uses_sheet_modifiers(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        goblin_hp_before = state.combatants["goblin"].hp

        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin")

        self.assertFalse(result.combat_over)
        # 1d10 (fighter) +3 STR +3 prof with roll 6 => 16 damage
        self.assertEqual(state.combatants["goblin"].hp, goblin_hp_before - 12)
        self.assertEqual(state.active_name, "Goblin")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_dodge_halves_damage(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)

        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        hero_hp_before = hero.hp

        with patch("combat.engine.random.randint", return_value=6):
            play_card(state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero")

        self.assertEqual(hero.hp, hero_hp_before - 3)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_spell_damage_from_srd(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt", damage_roll="1d10")
        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        card_id = spell_card_id("fire-bolt")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", return_value=8):
            result = play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")

        self.assertEqual(state.combatants["goblin"].hp, 20 - 8)
        self.assertIn("💫 Force", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_healing_spell_updates_sheet_hp(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("cure-wounds", level=1, damage_roll="2d8", healing=True)
        save_sheet(
            user_id=1,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Cleric",
                level=3,
                hp_current=10,
                hp_max=20,
                abilities={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 16, "cha": 10},
                spells=["cure-wounds"],
            ),
        )
        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        card_id = spell_card_id("cure-wounds")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", side_effect=[4, 5]):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")

        self.assertGreater(hero.hp, 10)
        sheet = get_sheet(user_id=1)
        assert sheet is not None
        self.assertEqual(sheet.hp_current, hero.hp)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_leveled_spell_uses_spell_slot(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("magic-missile", level=1, damage_roll="1d4 + 1")
        save_sheet(
            user_id=1,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={"str": 8, "dex": 14, "con": 12, "int": 16, "wis": 10, "cha": 10},
                spells=["magic-missile"],
                spell_slots=SpellSlots.from_dict({"maximum": {"1": 4}, "current": {"1": 4}}),
            ),
        )
        state = await start_combat(guild_id=self.guild_id, channel_id=self.channel_id)
        hero = state.combatants["hero"]
        card_id = spell_card_id("magic-missile")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", return_value=3):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")

        sheet = get_sheet(user_id=1)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 3)


class TestCombatStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_round_trip_with_catalog(self) -> None:
        from combat.cards import CardSnapshot

        weapon = CardSnapshot(
            card_id=WEAPON_CARD_ID,
            label="Weapon Attack",
            emoji="⚔️",
            description="Test",
            needs_target=True,
            target_enemies_only=True,
            card_type="weapon",
            dice_count=1,
            dice_sides=8,
            uses_proficiency=True,
            ability="str",
        )
        state = CombatState(
            guild_id=7,
            channel_id=3,
            turn_order=["A"],
            active_index=0,
            combatants={
                "a": CombatantState(
                    name="A",
                    user_id=None,
                    hp=10,
                    max_hp=10,
                    hand=[WEAPON_CARD_ID],
                    deck=[DODGE_CARD_ID],
                    card_catalog={WEAPON_CARD_ID: weapon},
                )
            },
            log=["Started"],
        )
        save_combat(state)
        loaded = get_combat(guild_id=7)
        assert loaded is not None
        self.assertEqual(loaded.combatants["a"].card_catalog[WEAPON_CARD_ID].label, "Weapon Attack")
