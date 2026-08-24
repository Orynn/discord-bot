import unittest

from combat.cards import DODGE_CARD_ID, WEAPON_CARD_ID, CardSnapshot, spell_card_id
from combat.view import (
    COMBAT_END_TURN_ID,
    COMBAT_HAND_ID,
    COMBAT_SELECT_ID,
    PersistentCombatBoardView,
    build_hand_select_options,
    build_play_select_options,
)


class TestHandSelectOptions(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = {
            WEAPON_CARD_ID: CardSnapshot(
                card_id=WEAPON_CARD_ID,
                label="Weapon Attack",
                emoji="⚔️",
                description="Attack",
                needs_target=True,
                target_enemies_only=True,
            ),
            DODGE_CARD_ID: CardSnapshot(
                card_id=DODGE_CARD_ID,
                label="Dodge",
                emoji="🤸",
                description="Dodge",
                needs_target=False,
            ),
        }

    def test_deduplicates_duplicate_cards(self) -> None:
        hand = [WEAPON_CARD_ID, WEAPON_CARD_ID, WEAPON_CARD_ID, DODGE_CARD_ID]
        options = build_hand_select_options(hand, self.catalog)
        values = [option[0] for option in options]
        self.assertEqual(values, [WEAPON_CARD_ID, DODGE_CARD_ID])
        self.assertIn("×3", options[0][1])

    def test_combat_embed_uses_emoji_title(self) -> None:
        from combat.display import build_combat_embed
        from combat.storage import CombatState, CombatantState

        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["hero"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=10,
                    max_hp=20,
                    hand=[],
                    deck=[],
                )
            },
        )
        embed = build_combat_embed(state)
        self.assertIn("🃏", embed.title)
        self.assertIn("⚔️ Combatants", [field.name for field in embed.fields])
        self.assertIn("❤️", embed.fields[0].value)
        self.assertIn("**Hero**", embed.fields[0].value)

    def test_monster_hp_is_hidden_on_the_board(self) -> None:
        from combat.display import format_combatants
        from combat.storage import CombatState, CombatantState

        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=10,
                    max_hp=20,
                    hand=[],
                    deck=[],
                ),
                "goblin": CombatantState(
                    name="Goblin",
                    user_id=None,
                    hp=30,
                    max_hp=30,
                    hand=[],
                    deck=[],
                    traits=["Nimble Escape"],
                ),
            },
        )
        board = format_combatants(state)
        self.assertIn("❤️ **10/20**", board)
        self.assertIn("**Goblin**", board)
        self.assertNotIn("30", board)
        self.assertIn("Nimble Escape", board)

    def test_play_menu_includes_spells_not_in_hand(self) -> None:
        poison = spell_card_id("poison-spray")
        catalog = {
            **self.catalog,
            poison: CardSnapshot(
                card_id=poison,
                label="Poison Spray",
                emoji="☠️",
                description="Cantrip",
                needs_target=True,
                target_enemies_only=True,
                card_type="spell",
            ),
        }
        options = build_play_select_options([WEAPON_CARD_ID], catalog)
        values = [option[0] for option in options[0]]
        self.assertEqual(values, [WEAPON_CARD_ID, poison])
        self.assertEqual(options[1:], (0, 1))

    def test_limits_to_25_unique_options(self) -> None:
        hand = [WEAPON_CARD_ID] * 30
        options = build_hand_select_options(hand, self.catalog)
        self.assertEqual(len(options), 1)

    def test_spellbook_paginates_past_discord_limit(self) -> None:
        catalog = dict(self.catalog)
        for index in range(40):
            card_id = spell_card_id(f"spell-{index:02d}")
            catalog[card_id] = CardSnapshot(
                card_id=card_id,
                label=f"Spell {index:02d}",
                emoji="✨",
                description="Cantrip",
                needs_target=True,
                target_enemies_only=True,
                card_type="spell",
            )
        page0, page, count = build_play_select_options(
            [WEAPON_CARD_ID], catalog, page=0
        )
        self.assertEqual(page, 0)
        self.assertGreater(count, 1)
        self.assertEqual(len(page0), 25)
        self.assertEqual(page0[0][0], WEAPON_CARD_ID)
        page1, page, count2 = build_play_select_options(
            [WEAPON_CARD_ID], catalog, page=1
        )
        self.assertEqual(page, 1)
        self.assertEqual(count, count2)
        self.assertEqual(page1[0][0], WEAPON_CARD_ID)
        self.assertNotEqual(
            {item[0] for item in page0[1:]}, {item[0] for item in page1[1:]}
        )

        from combat.storage import CombatState, CombatantState
        from combat.view import CombatBoardView

        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=10,
                    max_hp=20,
                    hand=[WEAPON_CARD_ID],
                    deck=[],
                    card_catalog=catalog,
                )
            },
        )
        view = CombatBoardView(state)
        labels = [getattr(item, "label", None) for item in view.children]
        self.assertIn("Spells ▶", labels)
        self.assertIn("◀ Spells", labels)

    def test_dying_player_shows_death_saves(self) -> None:
        from combat.display import format_combatants
        from combat.storage import CombatState, CombatantState

        state = CombatState(
            guild_id=1,
            channel_id=2,
            turn_order=["Hero", "Goblin"],
            active_index=0,
            combatants={
                "hero": CombatantState(
                    name="Hero",
                    user_id=1,
                    hp=0,
                    max_hp=20,
                    hand=[],
                    deck=[],
                    death_save_successes=1,
                    death_save_failures=2,
                ),
                "goblin": CombatantState(
                    name="Goblin",
                    user_id=None,
                    hp=0,
                    max_hp=30,
                    hand=[],
                    deck=[],
                ),
            },
        )
        board = format_combatants(state)
        self.assertIn("dying 1S/2F", board)
        self.assertIn("❤️ **0/20**", board)
        self.assertIn("**Goblin**", board)
        self.assertIn("💀", board)
        self.assertNotIn("30", board)

    def test_persistent_view_uses_stable_custom_ids(self) -> None:
        view = PersistentCombatBoardView()
        custom_ids = [item.custom_id for item in view.children]
        self.assertEqual(
            custom_ids, [COMBAT_SELECT_ID, COMBAT_END_TURN_ID, COMBAT_HAND_ID]
        )
        self.assertNotIn("0", COMBAT_SELECT_ID)
