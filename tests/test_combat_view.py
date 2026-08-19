import unittest

from combat.cards import DODGE_CARD_ID, WEAPON_CARD_ID, CardSnapshot
from combat.view import build_hand_select_options


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

    def test_limits_to_25_unique_options(self) -> None:
        hand = [WEAPON_CARD_ID] * 30
        options = build_hand_select_options(hand, self.catalog)
        self.assertEqual(len(options), 1)
