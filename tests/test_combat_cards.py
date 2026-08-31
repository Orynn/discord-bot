import unittest

from combat.cards import (
    DEFAULT_SPELL_RANGE_SQUARES,
    card_makes_attack_roll,
    parse_damage_roll,
    parse_range_squares,
)
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

    def test_save_spell_from_5etools_fields(self) -> None:
        sheet = CharacterSheet(name="Wiz", char_class="Wizard")
        card = _spell_card(
            sheet,
            {
                "slug": "fireball",
                "name": "Fireball",
                "level": 3,
                "school": "Evocation",
                "desc": "taking 8d6 Fire damage on a failed save or half as much damage on a successful one.",
                "entries": [
                    "Each creature makes a Dexterity saving throw, taking {@damage 8d6} Fire damage on a failed save or half as much damage on a successful one."
                ],
                "damageInflict": ["fire"],
                "savingThrow": ["dexterity"],
            },
        )
        assert card is not None
        self.assertEqual(card.save_ability, "dex")
        self.assertTrue(card.save_half)
        self.assertEqual(card.dice_count, 8)
        self.assertEqual(card.dice_sides, 6)
        self.assertFalse(card_makes_attack_roll(card))
        self.assertIn("DEX save", card.description)

    def test_condition_save_has_no_attack_roll(self) -> None:
        sheet = CharacterSheet(name="Wiz", char_class="Wizard")
        card = _spell_card(
            sheet,
            {
                "slug": "hold-person",
                "name": "Hold Person",
                "level": 2,
                "school": "Enchantment",
                "desc": "Wisdom saving throw or Paralyzed.",
                "savingThrow": ["wisdom"],
                "conditionInflict": ["paralyzed"],
            },
        )
        assert card is not None
        self.assertEqual(card.save_ability, "wis")
        self.assertEqual(card.inflict_condition, "paralyzed")
        self.assertEqual(card.dice_count, 0)
        self.assertFalse(card_makes_attack_roll(card))
        self.assertEqual(card.range_squares, DEFAULT_SPELL_RANGE_SQUARES)


class TestParseRangeSquares(unittest.TestCase):
    def test_melee_and_touch(self) -> None:
        self.assertEqual(parse_range_squares("Melee"), 1)
        self.assertEqual(parse_range_squares("Touch"), 1)

    def test_self_is_zero(self) -> None:
        self.assertEqual(parse_range_squares("Self"), 0)
        self.assertEqual(parse_range_squares("Self (30-foot radius)"), 0)

    def test_feet_and_weapon_range(self) -> None:
        self.assertEqual(parse_range_squares("120 feet"), 24)
        self.assertEqual(parse_range_squares("80/320 ft."), 16)
        self.assertEqual(parse_range_squares("30 ft."), 6)

    def test_unknown_is_unlimited(self) -> None:
        self.assertIsNone(parse_range_squares(None))
        self.assertIsNone(parse_range_squares("Sight"))
