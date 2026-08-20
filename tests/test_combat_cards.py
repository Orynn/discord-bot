import unittest

from combat.cards import parse_damage_roll
from combat.deck import _spell_card
from sheets.data import CharacterSheet


class TestParseDamageRoll(unittest.TestCase):
    def test_simple_dice(self) -> None:
        self.assertEqual(parse_damage_roll("8d6"), (8, 6, 0))

    def test_dice_with_flat_bonus(self) -> None:
        self.assertEqual(parse_damage_roll("1d4 + 1"), (1, 4, 1))

    def test_healing_roll(self) -> None:
        self.assertEqual(parse_damage_roll("2d8"), (2, 8, 0))

    def test_empty(self) -> None:
        self.assertEqual(parse_damage_roll(None), (0, 0, 0))


class TestSpellCard(unittest.TestCase):
    def test_formatted_cantrip_level_and_no_double_damage(self) -> None:
        sheet = CharacterSheet(name="Wiz", char_class="Wizard")
        card = _spell_card(
            sheet,
            {
                "slug": "magic-missile",
                "name": "Magic Missile",
                "level": "Cantrip",
                "school": "Evocation",
                "desc": "Deal damage.",
                "damage_roll": "1d4 + 1",
            },
        )
        assert card is not None
        self.assertEqual(card.spell_level, 0)
        self.assertIn("damage (SRD).", card.description)
        self.assertNotIn("damage damage", card.description)

    def test_damage_inflict_label(self) -> None:
        sheet = CharacterSheet(name="Wiz", char_class="Wizard")
        card = _spell_card(
            sheet,
            {
                "slug": "fire-bolt",
                "name": "Fire Bolt",
                "level": 0,
                "school": "Evocation",
                "desc": "Deal damage.",
                "damage_roll": "1d10",
                "damageInflict": ["fire"],
            },
        )
        assert card is not None
        self.assertIn("🔥 Fire damage", card.description)

    def test_utility_spell_has_no_damage_dice(self) -> None:
        sheet = CharacterSheet(name="Wiz", char_class="Wizard")
        card = _spell_card(
            sheet,
            {
                "slug": "mage-armor",
                "name": "Mage Armor",
                "level": 1,
                "school": "Abjuration",
                "desc": "You touch a willing creature who isn't wearing armor.",
            },
        )
        assert card is not None
        self.assertEqual(card.dice_count, 0)
        self.assertTrue(card.needs_target)
        self.assertTrue(card.target_allies_only)
        self.assertEqual(card.buff, "mage-armor")
        self.assertIn("1d4", card.description)
        self.assertFalse(card.is_healing)
