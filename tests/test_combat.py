import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import data.db as db_module
from combat.cards import DODGE_CARD_ID, HAND_SIZE, WEAPON_CARD_ID, spell_card_id
from combat.engine import (
    can_control_combatant,
    end_turn,
    play_card,
    start_combat,
    valid_targets,
)
from combat.storage import (
    CombatState,
    CombatantState,
    clear_combat,
    get_combat,
    save_combat,
)
from initiative.storage import InitiativeEntry, InitiativeState, save_initiative
from sheets.data import CharacterSheet
from sheets.spell_slots import SpellSlots
from sheets.storage import get_sheet, save_sheet


def _mock_spell(
    slug: str, *, level: int = 0, damage_roll: str = "1d8", healing: bool = False
) -> dict:
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
    scope_id = 1

    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()
        clear_combat(guild_id=self.guild_id)

        save_initiative(
            guild_id=self.guild_id,
            scope_id=self.scope_id,
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
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Fighter",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 16,
                    "dex": 12,
                    "con": 14,
                    "int": 10,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["fire-bolt"],
            ),
        )
        self._monster_patcher = patch(
            "combat.engine.lookup_monster_profile",
            new_callable=AsyncMock,
            return_value=None,
        )
        self._lookup_monster = self._monster_patcher.start()
        self.addCleanup(self._monster_patcher.stop)

    async def asyncTearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_start_combat_builds_sheet_deck(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")

        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]

        self.assertIn(WEAPON_CARD_ID, hero.card_catalog)
        self.assertIn(DODGE_CARD_ID, hero.card_catalog)
        self.assertIn(spell_card_id("fire-bolt"), hero.card_catalog)
        self.assertEqual(len(hero.hand), HAND_SIZE)
        self.assertIn(WEAPON_CARD_ID, goblin.card_catalog)
        self.assertNotIn(spell_card_id("fire-bolt"), goblin.card_catalog)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_weapon_attack_uses_sheet_modifiers(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        goblin_hp_before = state.combatants["goblin"].hp

        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )

        self.assertFalse(result.combat_over)
        # 1d10 (fighter) +3 STR +3 prof with roll 6 => 16 damage
        self.assertEqual(state.combatants["goblin"].hp, goblin_hp_before - 12)
        self.assertEqual(state.active_name, "Goblin")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_dodge_halves_damage(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)

        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        hero_hp_before = hero.hp

        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )

        self.assertEqual(hero.hp, hero_hp_before - 3)
        self.assertIn("Dodge: half", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_spell_damage_from_srd(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt", damage_roll="1d10")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("fire-bolt")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", return_value=8):
            result = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )

        self.assertEqual(state.combatants["goblin"].hp, 20 - 8)
        self.assertIn("💫 Force", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_healing_spell_updates_sheet_hp(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell(
            "cure-wounds", level=1, damage_roll="2d8", healing=True
        )
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Cleric",
                level=3,
                hp_current=10,
                hp_max=20,
                abilities={
                    "str": 10,
                    "dex": 10,
                    "con": 10,
                    "int": 10,
                    "wis": 16,
                    "cha": 10,
                },
                spells=["cure-wounds"],
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("cure-wounds")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", side_effect=[4, 5]):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")

        self.assertGreater(hero.hp, 10)
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.hp_current, hero.hp)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_leveled_spell_uses_spell_slot(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell(
            "magic-missile", level=1, damage_roll="1d4 + 1"
        )
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["magic-missile"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"1": 4}, "current": {"1": 4}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("magic-missile")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", return_value=3):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")

        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 3)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_healing_spell_cannot_target_enemy(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell(
            "cure-wounds", level=1, damage_roll="1d8", healing=True
        )
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Cleric",
                level=3,
                hp_current=10,
                hp_max=20,
                abilities={
                    "str": 10,
                    "dex": 10,
                    "con": 10,
                    "int": 10,
                    "wis": 16,
                    "cha": 10,
                },
                spells=["cure-wounds"],
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("cure-wounds")
        hero.hand = [card_id]
        targets = valid_targets(state, actor=hero, card_id=card_id)
        self.assertEqual([combatant.name for combatant in targets], ["Hero"])
        with self.assertRaises(ValueError):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")
        self.assertIn(card_id, hero.hand)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_warlock_uses_pact_slot_for_lower_level_spell(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("hex", level=1, damage_roll="1d6")
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Warlock",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 10,
                    "wis": 10,
                    "cha": 16,
                },
                spells=["hex"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"3": 2}, "current": {"3": 2}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("hex")
        hero.hand = [card_id]
        with patch("combat.engine.random.randint", return_value=4):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 0)
        self.assertEqual(sheet.spell_slots.get_current(3), 1)

    def test_only_admin_controls_npc_turns(self) -> None:
        goblin = CombatantState(
            name="Goblin",
            user_id=None,
            hp=10,
            max_hp=10,
            hand=[],
            deck=[],
        )
        hero = CombatantState(
            name="Hero",
            user_id=1,
            hp=10,
            max_hp=10,
            hand=[],
            deck=[],
        )
        self.assertTrue(
            can_control_combatant(combatant=goblin, user_id=99, is_admin=True)
        )
        self.assertFalse(
            can_control_combatant(combatant=goblin, user_id=99, is_admin=False)
        )
        self.assertTrue(
            can_control_combatant(
                combatant=goblin, user_id=1, is_admin=False, scope_id=1
            )
        )
        self.assertFalse(
            can_control_combatant(
                combatant=goblin, user_id=2, is_admin=False, scope_id=1
            )
        )
        self.assertTrue(
            can_control_combatant(combatant=hero, user_id=1, is_admin=False)
        )
        self.assertFalse(
            can_control_combatant(combatant=hero, user_id=2, is_admin=True)
        )

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_end_turn_does_not_grow_hand_past_limit(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID] * HAND_SIZE
        goblin.deck = [DODGE_CARD_ID] * 4
        state.active_index = 1
        end_turn(state, actor_name="Goblin")
        self.assertEqual(len(goblin.hand), HAND_SIZE)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_weapon_cannot_target_ally(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        save_sheet(
            user_id=2,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Ally", char_class="Fighter", level=1, hp_current=20, hp_max=20
            ),
        )
        save_initiative(
            guild_id=self.guild_id,
            scope_id=self.scope_id,
            state=InitiativeState(
                channel_id=self.channel_id,
                active_index=0,
                order=[
                    InitiativeEntry(name="Hero", total=18, user_id=1),
                    InitiativeEntry(name="Ally", total=15, user_id=2),
                    InitiativeEntry(name="Goblin", total=12, user_id=None),
                ],
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        targets = valid_targets(state, actor=hero, card_id=WEAPON_CARD_ID)
        self.assertEqual([combatant.name for combatant in targets], ["Goblin"])
        with self.assertRaises(ValueError) as raised:
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Ally"
            )
        self.assertIn("enemy", str(raised.exception).lower())
        self.assertIn(WEAPON_CARD_ID, hero.hand)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_party_wins_when_monsters_fall(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        save_sheet(
            user_id=2,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Ally", char_class="Fighter", level=1, hp_current=20, hp_max=20
            ),
        )
        save_initiative(
            guild_id=self.guild_id,
            scope_id=self.scope_id,
            state=InitiativeState(
                channel_id=self.channel_id,
                active_index=0,
                order=[
                    InitiativeEntry(name="Hero", total=18, user_id=1),
                    InitiativeEntry(name="Ally", total=15, user_id=2),
                    InitiativeEntry(name="Goblin", total=12, user_id=None),
                ],
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        state.combatants["goblin"].hp = 1
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertTrue(result.combat_over)
        self.assertEqual(result.winner, "the party")
        self.assertIn("party", result.message.lower())
        self.assertEqual(state.active_name, "Hero")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_played_cards_reshuffle_from_discard(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        hero.hand = [WEAPON_CARD_ID] * 4 + [DODGE_CARD_ID]
        hero.deck = [DODGE_CARD_ID]
        hero.discard = []
        goblin.hp = 500
        goblin.hand = [DODGE_CARD_ID]
        goblin.deck = [DODGE_CARD_ID] * 10

        for _ in range(6):
            card_id = hero.hand[0]
            if card_id == DODGE_CARD_ID:
                play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
            else:
                with patch("combat.engine.random.randint", return_value=1):
                    play_card(
                        state,
                        actor_name="Hero",
                        card_id=WEAPON_CARD_ID,
                        target_name="Goblin",
                    )
            self.assertTrue(hero.hand, "hand emptied — discard should reshuffle")
            goblin.hand = [DODGE_CARD_ID]
            end_turn(state, actor_name="Goblin")
        self.assertEqual(len(hero.hand), HAND_SIZE)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_utility_spell_plays_as_buff(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = {
            "key": "srd-2024_shield",
            "slug": "shield",
            "name": "Shield",
            "level": 1,
            "school": "Abjuration",
            "desc": "An invisible barrier of magical force appears.",
            "damage_roll": None,
            "damage_types": [],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["shield"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"1": 4}, "current": {"1": 4}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("shield")
        hero.hand = [card_id]
        hero.deck = [WEAPON_CARD_ID]
        hero.discard = []
        result = play_card(
            state, actor_name="Hero", card_id=card_id, target_name="Hero"
        )
        self.assertFalse(result.combat_over)
        self.assertIn("Shield", result.message)
        self.assertIn("negated", result.message)
        self.assertIn(card_id, hero.effects)
        self.assertIn(card_id, hero.discard)
        self.assertNotIn(card_id, hero.hand)
        self.assertIn(WEAPON_CARD_ID, hero.hand)
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 3)
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", return_value=6):
            blocked = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertIn("negated", blocked.message)
        self.assertEqual(hero.hp, 20)
        self.assertNotIn(card_id, hero.effects)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_mage_armor_reduces_hits(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = {
            "key": "srd-2024_mage-armor",
            "slug": "mage-armor",
            "name": "Mage Armor",
            "level": 1,
            "school": "Abjuration",
            "desc": "You touch a willing creature.",
            "damage_roll": None,
            "damage_types": [],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["mage-armor"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"1": 4}, "current": {"1": 4}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("mage-armor")
        hero.hand = [card_id]
        play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", side_effect=[6, 6, 2]):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertEqual(hero.hp, 16)
        self.assertIn("Mage Armor -2", result.message)
        self.assertIn(card_id, hero.effects)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_bless_adds_damage(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = {
            "key": "srd-2024_bless",
            "slug": "bless",
            "name": "Bless",
            "level": 1,
            "school": "Enchantment",
            "desc": "Bless up to three creatures.",
            "damage_roll": None,
            "damage_types": [],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Cleric",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 14,
                    "dex": 10,
                    "con": 12,
                    "int": 10,
                    "wis": 16,
                    "cha": 10,
                },
                spells=["bless"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"1": 4}, "current": {"1": 4}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("bless")
        hero.hand = [card_id]
        play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")
        goblin = state.combatants["goblin"]
        goblin.hand = [DODGE_CARD_ID]
        end_turn(state, actor_name="Goblin")
        hero.hand = [WEAPON_CARD_ID]
        goblin_hp = goblin.hp
        with patch("combat.engine.random.randint", side_effect=[6, 6, 3]):
            result = play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        # Cleric hit die d8: 6 +2 STR +2 prof +3 bless = 13
        self.assertEqual(goblin.hp, goblin_hp - 13)
        self.assertIn("Bless 3", result.message)

    @patch("combat.deck.fivetools.search_weapon", new_callable=AsyncMock)
    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_weapon_uses_equipped_dice(
        self,
        mock_get_spell: AsyncMock,
        mock_search_weapon: AsyncMock,
    ) -> None:
        from sheets.equipment import ITEM_KIND_WEAPON, Equipment, InventoryItem

        mock_get_spell.return_value = _mock_spell("fire-bolt")
        mock_search_weapon.return_value = {
            "name": "Dagger",
            "damage": "1d4",
            "damage_type": "🗡️ Piercing",
            "properties": "Finesse, Light, Thrown",
            "range": "Melee",
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Fighter",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 16,
                    "dex": 12,
                    "con": 14,
                    "int": 10,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["fire-bolt"],
                equipment=Equipment(
                    items=[
                        InventoryItem(
                            slug="",
                            name="Dagger",
                            kind=ITEM_KIND_WEAPON,
                            equipped=True,
                        )
                    ]
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        weapon = hero.card_catalog[WEAPON_CARD_ID]
        self.assertEqual(weapon.label, "Dagger")
        self.assertEqual(weapon.dice_sides, 4)
        hero.hand = [WEAPON_CARD_ID]
        goblin_hp = state.combatants["goblin"].hp
        with patch("combat.engine.random.randint", return_value=4):
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        # 1d4 +3 STR +3 prof = 10
        self.assertEqual(state.combatants["goblin"].hp, goblin_hp - 10)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_pack_tactics_adds_damage(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        goblin.traits = ["Pack Tactics"]
        state.combatants["wolf"] = CombatantState(
            name="Wolf",
            user_id=None,
            hp=11,
            max_hp=11,
            hand=[],
            deck=[],
            traits=["Pack Tactics"],
        )
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        goblin.hand = [WEAPON_CARD_ID]
        hero_hp = hero.hp
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        # claw 6 + pack 2 = 8, dodge half = 4
        self.assertEqual(hero.hp, hero_hp - 4)
        self.assertIn("Pack Tactics +2", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_spell_can_be_cast_from_spellbook(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("poison-spray", damage_roll="1d12")
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["poison-spray"],
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("poison-spray")
        hero.hand = [WEAPON_CARD_ID]
        hero.deck = [WEAPON_CARD_ID]
        hero.discard = []
        goblin_hp_before = state.combatants["goblin"].hp

        with patch("combat.engine.random.randint", return_value=9):
            result = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )

        self.assertEqual(state.combatants["goblin"].hp, goblin_hp_before - 9)
        self.assertNotIn("HP", result.message)
        self.assertIn(WEAPON_CARD_ID, hero.hand)
        self.assertNotIn(card_id, hero.discard)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_utility_spell_requires_a_target(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = {
            "key": "srd-2024_shield",
            "slug": "shield",
            "name": "Shield",
            "level": 1,
            "school": "Abjuration",
            "desc": "An invisible barrier of magical force appears.",
            "damage_roll": None,
            "damage_types": [],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=3,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["shield"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"1": 4}, "current": {"1": 4}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("shield")
        hero.hand = [card_id]
        with self.assertRaises(ValueError) as raised:
            play_card(state, actor_name="Hero", card_id=card_id)
        self.assertIn("target", str(raised.exception).lower())
        self.assertIn(card_id, hero.hand)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_attack_can_miss_armor_class(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        goblin.ac = 30
        hero.hand = [WEAPON_CARD_ID]
        goblin_hp = goblin.hp
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertEqual(goblin.hp, goblin_hp)
        self.assertIn("miss", result.message.lower())
        self.assertEqual(state.active_name, "Goblin")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_player_at_zero_hp_rolls_death_saves(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hp = 1
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertEqual(hero.hp, 0)
        self.assertIn("Hero", state.turn_order)
        self.assertEqual(hero.death_save_failures, 1)
        self.assertIn("dying", result.message.lower() + "\n".join(state.log).lower())
        self.assertEqual(state.active_name, "Goblin")
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.hp_current, 0)
        self.assertEqual(sheet.death_save_failures, 1)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_save_spell_deals_half_on_success(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = {
            "slug": "fireball",
            "name": "Fireball",
            "level": 3,
            "school": "Evocation",
            "desc": "2d6 Fire damage on a failed save or half as much damage on a successful one.",
            "damage_roll": "2d6",
            "damageInflict": ["fire"],
            "savingThrow": ["dexterity"],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["fireball"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"3": 2}, "current": {"3": 2}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("fireball")
        card = hero.card_catalog[card_id]
        self.assertEqual(card.save_ability, "dex")
        self.assertTrue(card.save_half)
        hero.hand = [card_id]
        goblin = state.combatants["goblin"]
        # DC 8+3+3=14. Save 6 fails (6 dmg). Save 18 succeeds (3 dmg).
        with patch("combat.engine.random.randint", side_effect=[6, 3, 3]):
            failed = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )
        self.assertEqual(goblin.hp, 20 - 6)
        self.assertIn("fail", failed.message)
        self.assertIn("🔥 Fire", failed.message)

        goblin.hp = 20
        hero.hand = [card_id]
        goblin.hand = [DODGE_CARD_ID]
        end_turn(state, actor_name="Goblin")
        with patch("combat.engine.random.randint", side_effect=[18, 3, 3]):
            saved = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )
        self.assertEqual(goblin.hp, 20 - 3)
        self.assertIn("success", saved.message)
        self.assertIn("half", saved.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_save_condition_applies_on_a_failed_save(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = {
            "slug": "hold-person",
            "name": "Hold Person",
            "level": 2,
            "school": "Enchantment",
            "desc": "The target must succeed on a Wisdom saving throw or have the Paralyzed condition.",
            "savingThrow": ["wisdom"],
            "conditionInflict": ["paralyzed"],
        }
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Wizard",
                level=5,
                hp_current=20,
                hp_max=20,
                abilities={
                    "str": 8,
                    "dex": 14,
                    "con": 12,
                    "int": 16,
                    "wis": 10,
                    "cha": 10,
                },
                spells=["hold-person"],
                spell_slots=SpellSlots.from_dict(
                    {"maximum": {"2": 2}, "current": {"2": 2}}
                ),
            ),
        )
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        card_id = spell_card_id("hold-person")
        hero.hand = [card_id]
        goblin = state.combatants["goblin"]
        with patch("combat.engine.random.randint", return_value=4):
            result = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )
        self.assertIn("paralyzed", goblin.conditions)
        self.assertIn("fail", result.message)
        self.assertIn("skips", "\n".join(state.log).lower())
        self.assertEqual(state.active_name, "Hero")


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
            scope_id=9,
            turn_order=["A"],
            active_index=0,
            combatants={
                "a": CombatantState(
                    name="A",
                    user_id=None,
                    hp=10,
                    max_hp=10,
                    hand=[WEAPON_CARD_ID],
                    deck=[],
                    discard=[DODGE_CARD_ID],
                    card_catalog={WEAPON_CARD_ID: weapon},
                )
            },
            log=["Started"],
        )
        save_combat(state)
        loaded = get_combat(guild_id=7, scope_id=9)
        self.assertIsNone(get_combat(guild_id=7, scope_id=1))
        assert loaded is not None
        self.assertEqual(
            loaded.combatants["a"].card_catalog[WEAPON_CARD_ID].label, "Weapon Attack"
        )
        self.assertEqual(loaded.combatants["a"].discard, [DODGE_CARD_ID])

    def test_combats_are_isolated_per_player_section(self) -> None:
        first = CombatState(
            guild_id=7,
            channel_id=3,
            scope_id=11,
            turn_order=["Fox"],
            active_index=0,
            combatants={
                "fox": CombatantState(
                    name="Fox",
                    user_id=11,
                    hp=10,
                    max_hp=10,
                    hand=[],
                    deck=[],
                )
            },
        )
        second = CombatState(
            guild_id=7,
            channel_id=4,
            scope_id=22,
            turn_order=["Max"],
            active_index=0,
            combatants={
                "max": CombatantState(
                    name="Max",
                    user_id=22,
                    hp=12,
                    max_hp=12,
                    hand=[],
                    deck=[],
                )
            },
        )
        save_combat(first)
        save_combat(second)
        loaded_first = get_combat(guild_id=7, scope_id=11)
        loaded_second = get_combat(guild_id=7, scope_id=22)
        assert loaded_first is not None and loaded_second is not None
        self.assertEqual(list(loaded_first.combatants), ["fox"])
        self.assertEqual(list(loaded_second.combatants), ["max"])
        clear_combat(guild_id=7, scope_id=11)
        self.assertIsNone(get_combat(guild_id=7, scope_id=11))
        self.assertIsNotNone(get_combat(guild_id=7, scope_id=22))

    def test_scope_id_comes_from_player_channel(self) -> None:
        from unittest.mock import MagicMock

        from combat.scope import scope_id_for_channel
        from players.storage import save_player_section

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
