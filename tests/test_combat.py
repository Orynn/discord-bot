import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import data.db as db_module
from combat.cards import (
    DODGE_CARD_ID,
    HAND_SIZE,
    WEAPON_CARD_ID,
    CardSnapshot,
    spell_card_id,
)
from combat.engine import (
    add_combatant,
    apply_hp_to_live_combat,
    can_control_combatant,
    end_turn,
    map_attack,
    play_card,
    start_combat,
    valid_targets,
)
from combat.map import cell_label
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


def _close_melee(state: CombatState) -> CombatState:
    pcs = [
        state.combatants[name.lower()]
        for name in state.turn_order
        if state.combatants[name.lower()].user_id is not None
    ]
    npcs = [
        state.combatants[name.lower()]
        for name in state.turn_order
        if state.combatants[name.lower()].user_id is None
    ]
    for index, combatant in enumerate(pcs):
        combatant.x = 2
        combatant.y = min(7, 3 + index)
    for index, combatant in enumerate(npcs):
        combatant.x = 3
        combatant.y = min(7, 3 + index)
    return state


class TestCombatEngine(unittest.IsolatedAsyncioTestCase):
    guild_id = 42
    channel_id = 99
    scope_id = 1

    async def _start(self) -> CombatState:
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        return _close_melee(state)

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
    async def test_start_combat_keeps_board_message_id(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        save_combat(
            CombatState(
                guild_id=self.guild_id,
                channel_id=self.channel_id,
                scope_id=self.scope_id,
                board_message_id=9001,
                turn_order=["Hero"],
                active_index=0,
                combatants={
                    "hero": CombatantState(
                        name="Hero",
                        user_id=1,
                        hp=8,
                        max_hp=8,
                        hand=[],
                        deck=[],
                    )
                },
            )
        )
        state = await start_combat(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            scope_id=self.scope_id,
        )
        self.assertEqual(state.board_message_id, 9001)
        loaded = get_combat(guild_id=self.guild_id, scope_id=self.scope_id)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 9001)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_start_combat_builds_sheet_deck(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")

        state = await self._start()
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
        state = await self._start()
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
        self.assertEqual(state.active_name, "Hero")
        self.assertTrue(hero.acted)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_dodge_halves_damage(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        hero = state.combatants["hero"]
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        end_turn(state, actor_name="Hero")

        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        hero_hp_before = hero.hp

        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )

        self.assertEqual(hero.hp, hero_hp_before - 3)
        self.assertIn("Esquive : moitié", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_spell_damage_from_srd(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt", damage_roll="1d10")
        state = await self._start()
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
        state = await self._start()
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
        state = await self._start()
        hero = state.combatants["hero"]
        card_id = spell_card_id("magic-missile")
        hero.hand = [card_id]

        with patch("combat.engine.random.randint", return_value=3):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")

        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 3)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_healing_spell_can_target_enemy(
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
        state = await self._start()
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        goblin.hp = 4
        card_id = spell_card_id("cure-wounds")
        hero.hand = [card_id]
        targets = valid_targets(state, actor=hero, card_id=card_id)
        self.assertEqual({combatant.name for combatant in targets}, {"Hero", "Goblin"})
        with patch("combat.engine.random.randint", return_value=6):
            play_card(state, actor_name="Hero", card_id=card_id, target_name="Goblin")
        self.assertGreater(goblin.hp, 4)
        self.assertNotIn(card_id, hero.hand)

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
        state = await self._start()
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
        mock_pc = CombatantState(
            name="Mock",
            user_id=-404,
            hp=44,
            max_hp=44,
            hand=[],
            deck=[],
        )
        self.assertTrue(
            can_control_combatant(combatant=mock_pc, user_id=2, is_admin=False)
        )

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_end_turn_does_not_grow_hand_past_limit(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID] * HAND_SIZE
        goblin.deck = [DODGE_CARD_ID] * 4
        state.active_index = 1
        end_turn(state, actor_name="Goblin")
        self.assertEqual(len(goblin.hand), HAND_SIZE)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_weapon_can_target_ally(self, mock_get_spell: AsyncMock) -> None:
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
        state = await self._start()
        hero = state.combatants["hero"]
        ally = state.combatants["ally"]
        hero.hand = [WEAPON_CARD_ID]
        targets = valid_targets(state, actor=hero, card_id=WEAPON_CARD_ID)
        self.assertEqual(
            {combatant.name for combatant in targets}, {"Ally", "Goblin"}
        )
        ally_hp = ally.hp
        with patch("combat.engine.random.randint", return_value=6):
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Ally"
            )
        self.assertLess(ally.hp, ally_hp)
        self.assertNotIn(WEAPON_CARD_ID, hero.hand)
        hero.acted = False
        with self.assertRaises(ValueError) as raised:
            map_attack(state, actor_name="Hero", target_name="Hero")
        self.assertIn("toi-même", str(raised.exception))

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
        state = await self._start()
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        state.combatants["goblin"].hp = 1
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertTrue(result.combat_over)
        self.assertEqual(result.winner, "the party")
        self.assertIn("groupe", result.message.lower())
        self.assertEqual(state.active_name, "Hero")
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_last_monster_ko_ends_combat(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        state.combatants["goblin"].hp = 1
        with patch("combat.engine.random.randint", return_value=20):
            result = map_attack(state, actor_name="Hero", target_name="Goblin")
        self.assertEqual(state.combatants["goblin"].hp, 0)
        self.assertTrue(result.combat_over)
        self.assertIn("remporte", result.message.lower())
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_one_monster_ko_keeps_combat_until_last(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        wolf = await add_combatant(state, name="Wolf", hp=8)
        wolf.x, wolf.y = 2, 4
        state.combatants["goblin"].hp = 1
        with patch("combat.engine.random.randint", return_value=20):
            first = map_attack(state, actor_name="Hero", target_name="Goblin")
        self.assertFalse(first.combat_over)
        self.assertIsNotNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))
        state.combatants["hero"].acted = False
        state.combatants["wolf"].hp = 1
        with patch("combat.engine.random.randint", return_value=20):
            second = map_attack(state, actor_name="Hero", target_name="Wolf")
        self.assertTrue(second.combat_over)
        self.assertIn("remporte", second.message.lower())
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_played_cards_reshuffle_from_discard(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
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
            end_turn(state, actor_name="Hero")
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
        state = await self._start()
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
        self.assertIn("annulé", result.message)
        self.assertIn(card_id, hero.effects)
        self.assertIn(card_id, hero.discard)
        self.assertNotIn(card_id, hero.hand)
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.spell_slots.get_current(1), 3)
        end_turn(state, actor_name="Hero")
        self.assertIn(WEAPON_CARD_ID, hero.hand)
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", return_value=6):
            blocked = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertIn("annulé", blocked.message)
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
        state = await self._start()
        hero = state.combatants["hero"]
        card_id = spell_card_id("mage-armor")
        hero.hand = [card_id]
        play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")
        end_turn(state, actor_name="Hero")
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", side_effect=[6, 6, 2]):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertEqual(hero.hp, 16)
        self.assertIn("Armure du mage -2", result.message)
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
        state = await self._start()
        hero = state.combatants["hero"]
        card_id = spell_card_id("bless")
        hero.hand = [card_id]
        play_card(state, actor_name="Hero", card_id=card_id, target_name="Hero")
        end_turn(state, actor_name="Hero")
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
        state = await self._start()
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
        state = await self._start()
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
        end_turn(state, actor_name="Hero")
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
        state = await self._start()
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
        state = await self._start()
        hero = state.combatants["hero"]
        card_id = spell_card_id("shield")
        hero.hand = [card_id]
        with self.assertRaises(ValueError) as raised:
            play_card(state, actor_name="Hero", card_id=card_id)
        self.assertIn("cible", str(raised.exception).lower())
        self.assertIn(card_id, hero.hand)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_attack_can_miss_armor_class(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
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
        self.assertIn("raté", result.message.lower())
        self.assertEqual(state.active_name, "Hero")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_player_defeat_ends_combat(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        hero = state.combatants["hero"]
        hero.hp = 1
        hero.hand = [DODGE_CARD_ID]
        play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        end_turn(state, actor_name="Hero")
        goblin = state.combatants["goblin"]
        goblin.hand = [WEAPON_CARD_ID]
        with patch("combat.engine.random.randint", return_value=6):
            result = play_card(
                state, actor_name="Goblin", card_id=WEAPON_CARD_ID, target_name="Hero"
            )
        self.assertEqual(hero.hp, 0)
        self.assertTrue(result.combat_over)
        self.assertEqual(result.winner, "Goblin")
        self.assertIn("remporte", result.message.lower())
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.hp_current, 0)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_sandbox_start_restores_dying_player(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        save_sheet(
            user_id=1,
            guild_id=self.guild_id,
            sheet=CharacterSheet(
                name="Hero",
                char_class="Fighter",
                level=5,
                hp_current=0,
                hp_max=20,
                death_save_failures=2,
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
        state = await start_combat(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            scope_id=self.scope_id,
            restore_hp=True,
        )
        hero = state.combatants["hero"]
        self.assertEqual(hero.hp, 20)
        self.assertEqual(hero.death_save_failures, 0)
        self.assertEqual(state.active_name, "Hero")
        sheet = get_sheet(user_id=1, guild_id=self.guild_id)
        assert sheet is not None
        self.assertEqual(sheet.hp_current, 20)
        self.assertEqual(sheet.death_save_failures, 0)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_dying_player_action_ends_combat(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        hero = state.combatants["hero"]
        hero.hp = 0
        hero.hand = [DODGE_CARD_ID]
        result = play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        self.assertTrue(result.combat_over)
        self.assertEqual(result.winner, "Goblin")
        self.assertIn("remporte", result.message.lower())
        self.assertIsNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_downed_ally_does_not_end_combat(
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
        state = await self._start()
        state.combatants["ally"].hp = 0
        save_combat(state)
        hero = state.combatants["hero"]
        hero.hand = [DODGE_CARD_ID]
        result = play_card(state, actor_name="Hero", card_id=DODGE_CARD_ID)
        self.assertFalse(result.combat_over)
        self.assertIsNotNone(get_combat(guild_id=self.guild_id, scope_id=self.scope_id))

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_sheet_hp_revives_live_combatant(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        state.combatants["hero"].hp = 0
        state.combatants["hero"].death_save_failures = 2
        save_combat(state)
        name = apply_hp_to_live_combat(
            guild_id=self.guild_id,
            scope_id=self.scope_id,
            user_id=1,
            hp=12,
            max_hp=20,
        )
        self.assertEqual(name, "Hero")
        loaded = get_combat(guild_id=self.guild_id, scope_id=self.scope_id)
        assert loaded is not None
        self.assertEqual(loaded.combatants["hero"].hp, 12)
        self.assertEqual(loaded.combatants["hero"].death_save_failures, 0)

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
        state = await self._start()
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
        self.assertIn("échec", failed.message)
        self.assertIn("🔥 Fire", failed.message)

        goblin.hp = 20
        hero.hand = [card_id]
        goblin.hand = [DODGE_CARD_ID]
        end_turn(state, actor_name="Hero")
        end_turn(state, actor_name="Goblin")
        with patch("combat.engine.random.randint", side_effect=[18, 3, 3]):
            saved = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )
        self.assertEqual(goblin.hp, 20 - 3)
        self.assertIn("réussite", saved.message)
        self.assertIn("moitié", saved.message)

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
        state = await self._start()
        hero = state.combatants["hero"]
        card_id = spell_card_id("hold-person")
        hero.hand = [card_id]
        goblin = state.combatants["goblin"]
        with patch("combat.engine.random.randint", return_value=4):
            result = play_card(
                state, actor_name="Hero", card_id=card_id, target_name="Goblin"
            )
        self.assertIn("paralyzed", goblin.conditions)
        self.assertIn("échec", result.message)
        end_turn(state, actor_name="Hero")
        self.assertIn("passe", "\n".join(state.log).lower())
        self.assertEqual(state.active_name, "Hero")

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_aoe_hits_creatures_in_radius(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("fire-bolt")
        state = await self._start()
        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        extra = CombatantState(
            name="Wolf",
            user_id=None,
            hp=11,
            max_hp=11,
            hand=[],
            deck=[],
            x=goblin.x,
            y=(goblin.y or 3) + 1 if goblin.y is not None else 4,
        )
        state.combatants["wolf"] = extra
        state.turn_order.append("Wolf")
        card = CardSnapshot(
            card_id="spell:fireball",
            label="Fireball",
            emoji="🔥",
            description="AoE",
            needs_target=True,
            target_enemies_only=True,
            card_type="spell",
            dice_count=1,
            dice_sides=6,
            save_ability="dex",
            save_half=True,
            range_squares=24,
            aoe_radius=4,
        )
        hero.card_catalog[card.card_id] = card
        hero.hand = [card.card_id]
        center = cell_label(goblin.x, goblin.y)
        with patch("combat.engine.random.randint", return_value=4):
            result = play_card(
                state, actor_name="Hero", card_id=card.card_id, target_name=center
            )
        self.assertLess(goblin.hp, 20)
        self.assertLess(extra.hp, 11)
        self.assertIn("Fireball", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_new_concentration_drops_previous(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = _mock_spell("bless", level=1, damage_roll="")
        state = await self._start()
        hero = state.combatants["hero"]
        bless = CardSnapshot(
            card_id=spell_card_id("bless"),
            label="Bless",
            emoji="💫",
            description="buff",
            needs_target=True,
            target_allies_only=True,
            card_type="spell",
            spell_slug="bless",
            buff="bless",
            range_squares=6,
            concentration=True,
        )
        hold = CardSnapshot(
            card_id=spell_card_id("hold-person"),
            label="Hold Person",
            emoji="✨",
            description="hold",
            needs_target=True,
            target_enemies_only=True,
            card_type="spell",
            spell_slug="hold-person",
            save_ability="wis",
            inflict_condition="paralyzed",
            range_squares=12,
            concentration=True,
        )
        hero.card_catalog[bless.card_id] = bless
        hero.card_catalog[hold.card_id] = hold
        hero.hand = [bless.card_id, hold.card_id]
        play_card(state, actor_name="Hero", card_id=bless.card_id, target_name="Hero")
        self.assertEqual(hero.concentrating, bless.card_id)
        self.assertIn(bless.card_id, hero.effects)
        hero.acted = False
        with patch("combat.engine.random.randint", return_value=4):
            play_card(
                state, actor_name="Hero", card_id=hold.card_id, target_name="Goblin"
            )
        self.assertEqual(hero.concentrating, hold.card_id)
        self.assertNotIn(bless.card_id, hero.effects)
        self.assertIn("concentration", "\n".join(state.log).lower())


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
            board_message_id=4242,
        )
        save_combat(state)
        loaded = get_combat(guild_id=7, scope_id=9)
        self.assertIsNone(get_combat(guild_id=7, scope_id=1))
        assert loaded is not None
        self.assertEqual(
            loaded.combatants["a"].card_catalog[WEAPON_CARD_ID].label, "Weapon Attack"
        )
        self.assertEqual(loaded.combatants["a"].discard, [DODGE_CARD_ID])
        self.assertEqual(loaded.board_message_id, 4242)

    def test_board_message_id_optional_on_old_state(self) -> None:
        loaded = CombatState.from_dict(
            {
                "guild_id": 1,
                "channel_id": 2,
                "turn_order": [],
                "active_index": 0,
                "combatants": {},
            }
        )
        self.assertIsNone(loaded.board_message_id)

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

    def test_scope_id_uses_trash_channel_as_sandbox(self) -> None:
        from unittest.mock import MagicMock

        from combat.scope import scope_id_for_channel

        guild = MagicMock()
        guild.id = 7
        trash = MagicMock()
        trash.id = 404
        trash.name = "🚯trash"
        trash.category_id = 88
        trash.category = MagicMock(id=88, name="staff", channels=[])
        self.assertEqual(scope_id_for_channel(guild=guild, channel=trash), 404)
