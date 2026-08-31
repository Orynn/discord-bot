import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

import data.db as db_module
import sheets.portrait as portrait_module
from combat.cards import WEAPON_CARD_ID, CardSnapshot
from combat.engine import (
    add_combatant,
    end_turn,
    finish_turn,
    map_attack,
    move_combatant,
    play_card,
    start_combat,
)
from combat.map import (
    NPC_COLUMN,
    PC_COLUMN,
    apply_template,
    attack_targets_in_range,
    cell_label,
    chebyshev,
    ensure_positions,
    is_wall,
    parse_cell,
    parse_destination,
    path_length,
    targets_in_range,
)
from combat.render import (
    CELL,
    MARGIN_LEFT,
    MARGIN_TOP,
    circular_token,
    render_combat_map,
)
from combat.storage import CombatState, CombatantState, clear_combat, get_combat
from initiative.storage import InitiativeEntry, InitiativeState, save_initiative
from sheets.data import CharacterSheet
from sheets.storage import save_sheet


def _combatant(
    name: str,
    *,
    user_id: int | None,
    x: int | None = None,
    y: int | None = None,
    speed: int = 30,
    hp: int = 20,
) -> CombatantState:
    return CombatantState(
        name=name,
        user_id=user_id,
        hp=hp,
        max_hp=20,
        hand=[],
        deck=[],
        x=x,
        y=y,
        speed=speed,
        card_catalog={
            WEAPON_CARD_ID: CardSnapshot(
                card_id=WEAPON_CARD_ID,
                label="Weapon Attack",
                emoji="⚔️",
                description="Attack",
                needs_target=True,
                target_enemies_only=True,
                card_type="weapon",
                dice_count=1,
                dice_sides=6,
                ability="str",
                uses_proficiency=True,
            )
        },
    )


class TestMapHelpers(unittest.TestCase):
    def test_parse_cell_and_steps(self) -> None:
        self.assertEqual(parse_cell("C4"), (2, 3))
        self.assertEqual(parse_cell("a1"), (0, 0))
        actor = _combatant("Hero", user_id=1, x=1, y=3)
        self.assertEqual(parse_destination(actor, "C4"), (2, 3))
        self.assertEqual(parse_destination(actor, "2e"), (3, 3))
        self.assertEqual(parse_destination(actor, "north"), (1, 2))
        self.assertEqual(parse_destination(actor, "haut"), (1, 2))
        self.assertIsNone(parse_destination(actor, "nowhere"))
        wide = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero"],
            active_index=0,
            combatants={"hero": actor},
            map_width=12,
            map_height=10,
        )
        self.assertEqual(parse_cell("L10", wide), (11, 9))
        self.assertIsNone(parse_cell("L10", CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero"],
            active_index=0,
            combatants={"hero": actor},
        )))

    def test_layout_puts_pcs_left_npcs_right(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1),
                "goblin": _combatant("Goblin", user_id=None),
            },
        )
        ensure_positions(state)
        self.assertEqual(state.combatants["hero"].x, PC_COLUMN)
        self.assertEqual(state.combatants["goblin"].x, NPC_COLUMN)
        self.assertEqual(
            cell_label(state.combatants["hero"].x, state.combatants["hero"].y), "B4"
        )
        self.assertEqual(
            cell_label(state.combatants["goblin"].x, state.combatants["goblin"].y),
            "G4",
        )

    def test_path_blocked_by_enemy(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
                "goblin": _combatant("Goblin", user_id=None, x=2, y=3),
            },
        )
        hero = state.combatants["hero"]
        self.assertIsNone(path_length(state, hero, 2, 3))
        self.assertEqual(path_length(state, hero, 3, 3), 2)
        self.assertEqual(path_length(state, hero, 2, 2), 1)

    def test_attack_targets_include_allies(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Ally", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
                "ally": _combatant("Ally", user_id=2, x=2, y=3),
                "goblin": _combatant("Goblin", user_id=None, x=2, y=4),
            },
        )
        hero = state.combatants["hero"]
        self.assertEqual(
            {entry.name for entry in attack_targets_in_range(state, hero, 1)},
            {"Ally", "Goblin"},
        )
        self.assertEqual(
            {entry.name for entry in targets_in_range(state, hero, 1)},
            {"Goblin"},
        )

    def test_path_blocked_by_ally(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Ally"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
                "ally": _combatant("Ally", user_id=2, x=2, y=3),
            },
        )
        hero = state.combatants["hero"]
        self.assertIsNone(path_length(state, hero, 2, 3))
        self.assertEqual(path_length(state, hero, 3, 3), 2)

    def test_render_writes_png(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
                "goblin": _combatant("Goblin", user_id=None, x=6, y=3),
            },
        )
        png = render_combat_map(state)
        header = png.read(8)
        self.assertEqual(header, b"\x89PNG\r\n\x1a\n")

    def test_circular_token_is_round(self) -> None:
        src = Image.new("RGB", (80, 40), (255, 0, 0))
        token = circular_token(src, 32)
        self.assertEqual(token.size, (32, 32))
        self.assertEqual(token.getpixel((0, 0))[3], 0)
        self.assertGreater(token.getpixel((16, 16))[3], 200)
        self.assertGreater(token.getpixel((16, 16))[0], 200)

    def test_render_uses_player_portrait(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        original = portrait_module.PORTRAIT_DIR
        portrait_module.PORTRAIT_DIR = Path(tmpdir.name)
        try:
            Image.new("RGB", (48, 48), (255, 0, 0)).save(
                Path(tmpdir.name) / "1_1.png"
            )
            state = CombatState(
                guild_id=1,
                channel_id=2,
                turn_order=["Hero", "Goblin"],
                active_index=0,
                combatants={
                    "hero": _combatant("Hero", user_id=1, x=1, y=3),
                    "goblin": _combatant("Goblin", user_id=None, x=6, y=3),
                },
            )
            png = render_combat_map(state)
            rendered = Image.open(png)
            cx = MARGIN_LEFT + 1 * CELL + CELL // 2
            cy = MARGIN_TOP + 3 * CELL + CELL // 2 - 6
            pixel = rendered.getpixel((cx, cy))
            self.assertGreater(pixel[0], 200)
            self.assertLess(pixel[1], 40)
            self.assertLess(pixel[2], 40)
        finally:
            portrait_module.PORTRAIT_DIR = original
            tmpdir.cleanup()

    def test_grappled_blocks_movement(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
            },
        )
        state.combatants["hero"].conditions = ["grappled"]
        with self.assertRaises(ValueError) as raised:
            move_combatant(state, actor_name="Hero", dest_x=2, dest_y=3)
        self.assertIn("agrippé", str(raised.exception).lower())

    def test_opportunity_attack_when_leaving_melee(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=4, y=3, hp=20),
                "goblin": _combatant("Goblin", user_id=None, x=5, y=3),
            },
        )
        hero_hp = state.combatants["hero"].hp
        with patch("combat.engine.random.randint", return_value=15):
            result = move_combatant(state, actor_name="Hero", dest_x=3, dest_y=3)
        self.assertIn("opportunité", result.message.lower())
        self.assertLess(state.combatants["hero"].hp, hero_hp)
        self.assertEqual(state.combatants["hero"].x, 3)


class TestMapCombatEngine(unittest.IsolatedAsyncioTestCase):
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
                speed=30,
                abilities={
                    "str": 16,
                    "dex": 12,
                    "con": 14,
                    "int": 10,
                    "wis": 10,
                    "cha": 10,
                },
            ),
        )
        self._monster_patcher = patch(
            "combat.engine.lookup_monster_profile",
            new_callable=AsyncMock,
            return_value=None,
        )
        self._monster_patcher.start()
        self.addCleanup(self._monster_patcher.stop)

    async def asyncTearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_start_places_tokens(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        self.assertEqual(state.combatants["hero"].x, PC_COLUMN)
        self.assertEqual(state.combatants["goblin"].x, NPC_COLUMN)
        self.assertEqual(state.combatants["hero"].speed, 30)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_move_and_melee_attack(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        with self.assertRaises(ValueError):
            map_attack(state, actor_name="Hero", target_name="Goblin")

        result = move_combatant(state, actor_name="Hero", dest_x=5, dest_y=3)
        self.assertIn("F4", result.message)
        self.assertEqual(state.combatants["hero"].moved, 4)
        self.assertEqual(state.combatants["hero"].x, 5)

        goblin_hp = state.combatants["goblin"].hp
        with patch("combat.engine.random.randint", return_value=6):
            hit = map_attack(state, actor_name="Hero", target_name="Goblin")
        self.assertGreater(goblin_hp, state.combatants["goblin"].hp)
        self.assertTrue(state.combatants["hero"].acted)
        self.assertIn("Weapon", hit.message)
        self.assertEqual(state.active_name, "Hero")

        with self.assertRaises(ValueError):
            map_attack(state, actor_name="Hero", target_name="Goblin")
        state.combatants["hero"].hand = [WEAPON_CARD_ID]
        with self.assertRaises(ValueError) as raised:
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertIn("action", str(raised.exception).lower())

        passed = end_turn(state, actor_name="Hero")
        self.assertEqual(state.active_name, "Goblin")
        self.assertEqual(state.combatants["goblin"].moved, 0)
        self.assertFalse(state.combatants["goblin"].acted)
        self.assertIn("Goblin", passed.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_move_too_far_and_reload(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        state.combatants["hero"].speed = 10
        with self.assertRaises(ValueError):
            move_combatant(state, actor_name="Hero", dest_x=4, dest_y=3)
        move_combatant(state, actor_name="Hero", dest_x=3, dest_y=3)
        reloaded = get_combat(guild_id=self.guild_id, scope_id=self.scope_id)
        assert reloaded is not None
        self.assertEqual(reloaded.combatants["hero"].x, 3)
        self.assertEqual(reloaded.combatants["hero"].y, 3)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_add_places_new_monster(self, mock_get_spell: AsyncMock) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        wolf = await add_combatant(state, name="Wolf")
        self.assertEqual(wolf.x, NPC_COLUMN)
        self.assertIsNotNone(wolf.y)
        self.assertNotEqual(
            (wolf.x, wolf.y),
            (state.combatants["goblin"].x, state.combatants["goblin"].y),
        )

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_card_respects_range_and_keeps_turn(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hero.hand = [WEAPON_CARD_ID]
        with self.assertRaises(ValueError) as raised:
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertIn("portée", str(raised.exception).lower())
        self.assertIn(WEAPON_CARD_ID, hero.hand)
        self.assertFalse(hero.acted)
        self.assertEqual(state.active_name, "Hero")

        move_combatant(state, actor_name="Hero", dest_x=5, dest_y=3)
        with patch("combat.engine.random.randint", return_value=6):
            play_card(
                state, actor_name="Hero", card_id=WEAPON_CARD_ID, target_name="Goblin"
            )
        self.assertTrue(hero.acted)
        self.assertEqual(state.active_name, "Hero")

    def test_walls_block_straight_path(self) -> None:
        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": _combatant("Hero", user_id=1, x=1, y=3),
                "goblin": _combatant("Goblin", user_id=None, x=6, y=3),
            },
            blocked=[[2, 3]],
        )
        hero = state.combatants["hero"]
        self.assertTrue(is_wall(state, 2, 3))
        self.assertIsNone(path_length(state, hero, 2, 3))
        self.assertEqual(path_length(state, hero, 3, 3), 2)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_tavern_template_and_ranged_disadvantage(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = None
        state = await start_combat(
            guild_id=self.guild_id,
            channel_id=self.channel_id,
            scope_id=self.scope_id,
            map_id="tavern",
        )
        self.assertEqual(state.map_id, "tavern")
        self.assertTrue(state.blocked)
        for combatant in state.combatants.values():
            self.assertFalse(is_wall(state, combatant.x, combatant.y))
        apply_template(state, "dungeon")
        self.assertEqual(state.map_id, "dungeon")

        hero = state.combatants["hero"]
        goblin = state.combatants["goblin"]
        hero.x, hero.y = 2, 3
        goblin.x, goblin.y = 3, 3
        hero.card_catalog[WEAPON_CARD_ID] = replace(
            hero.card_catalog[WEAPON_CARD_ID], range_squares=6
        )
        with patch("combat.engine.random.randint", side_effect=[20, 1, 4]):
            result = map_attack(state, actor_name="Hero", target_name="Goblin")
        self.assertIn("désav", result.message)

    @patch("combat.deck.fivetools.get_spell", new_callable=AsyncMock)
    async def test_monsters_act_after_player_turn(
        self, mock_get_spell: AsyncMock
    ) -> None:
        mock_get_spell.return_value = None
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
        state = await start_combat(
            guild_id=self.guild_id, channel_id=self.channel_id, scope_id=self.scope_id
        )
        hero = state.combatants["hero"]
        hp_before = hero.hp
        with patch("combat.engine.random.randint", return_value=15):
            result = finish_turn(state, actor_name="Hero")
        goblin = state.combatants["goblin"]
        self.assertLessEqual(chebyshev(goblin.x, goblin.y, hero.x, hero.y), 1)
        self.assertLess(hero.hp, hp_before)
        self.assertEqual(state.active_name, "Hero")
        self.assertIn("déplace", result.message.lower())
