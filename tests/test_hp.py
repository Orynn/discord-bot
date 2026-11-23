import unittest

from sheets.data import CharacterSheet
from sheets.handlers import apply_hp, apply_hp_spec, format_hp_update


class TestApplyHpSpec(unittest.TestCase):
    def test_relative_damage_and_heal(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=14, hp_max=20)
        update = apply_hp_spec(sheet, "-4")
        self.assertEqual(update.delta, -4)
        self.assertEqual(sheet.hp_current, 10)
        self.assertIn("14 → 10", format_hp_update("Hero", update))
        self.assertIn("(-4)", format_hp_update("Hero", update))

        update = apply_hp_spec(sheet, "+6")
        self.assertEqual(sheet.hp_current, 16)
        self.assertEqual(update.delta, 6)

    def test_relative_cannot_go_below_zero(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=3, hp_max=20)
        apply_hp_spec(sheet, "-10")
        self.assertEqual(sheet.hp_current, 0)

    def test_absolute_and_slash_max(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=14, hp_max=20)
        apply_hp_spec(sheet, "12")
        self.assertEqual(sheet.hp_current, 12)
        apply_hp_spec(sheet, "12/30")
        self.assertEqual((sheet.hp_current, sheet.hp_max), (12, 30))
        apply_hp_spec(sheet, "8 18")
        self.assertEqual((sheet.hp_current, sheet.hp_max), (8, 18))

    def test_caps_heal_at_max(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=18, hp_max=20)
        update = apply_hp_spec(sheet, "+10")
        self.assertEqual(sheet.hp_current, 20)
        self.assertEqual(update.delta, 2)
        self.assertIn("(+2)", format_hp_update("Hero", update))

    def test_noop_relative_change_has_no_zero_delta(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=20, hp_max=20)
        update = apply_hp_spec(sheet, "+5")
        self.assertEqual(format_hp_update("Hero", update), "Hero: HP **20/20**.")

    def test_rejects_absolute_negative(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=10, hp_max=20)
        with self.assertRaises(ValueError):
            apply_hp(sheet, -1)


if __name__ == "__main__":
    unittest.main()
