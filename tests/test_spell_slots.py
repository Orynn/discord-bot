import unittest

from sheets.data import CharacterSheet
from sheets.spell_slots import SpellSlots, slots_table_for_class


class TestSpellSlots(unittest.TestCase):
    def test_use_and_recover(self) -> None:
        slots = SpellSlots()
        slots.set_level(1, 4)
        slots.set_level(2, 3)
        slots.use(1, 2)
        self.assertEqual(slots.get_current(1), 2)
        slots.recover(1, 1)
        self.assertEqual(slots.get_current(1), 3)
        slots.restore_all()
        self.assertEqual(slots.get_current(1), 4)
        self.assertEqual(slots.get_current(2), 3)

    def test_use_insufficient_raises(self) -> None:
        slots = SpellSlots()
        slots.set_level(1, 1)
        slots.use(1)
        with self.assertRaises(ValueError):
            slots.use(1)

    def test_format(self) -> None:
        slots = SpellSlots()
        slots.set_level(1, 4, 2)
        slots.set_level(3, 2)
        text = slots.format()
        self.assertIn("1st **2/4**", text)
        self.assertIn("3rd **2/2**", text)

    def test_from_dict_roundtrip(self) -> None:
        slots = SpellSlots()
        slots.set_level(1, 4, 3)
        slots.set_level(2, 2)
        restored = SpellSlots.from_dict(slots.to_dict())
        self.assertEqual(restored.get_current(1), 3)
        self.assertEqual(restored.get_maximum(2), 2)

    def test_auto_wizard_level_5(self) -> None:
        table = slots_table_for_class("Wizard", 5)
        assert table is not None
        self.assertEqual(table[:3], (4, 3, 2))

    def test_auto_warlock_level_5(self) -> None:
        table = slots_table_for_class("Warlock", 5)
        assert table is not None
        self.assertEqual(table[2], 2)  # two 3rd-level pact slots
        self.assertEqual(sum(table), 2)

    def test_sheet_long_rest_restores_slots(self) -> None:
        sheet = CharacterSheet(name="Lyra", char_class="Wizard", level=5)
        sheet.spell_slots.apply_table(slots_table_for_class("Wizard", 5))  # type: ignore[arg-type]
        sheet.spell_slots.use(1, 2)
        sheet.hp_max = 30
        sheet.hp_current = 10
        sheet.long_rest()
        self.assertEqual(sheet.hp_current, 30)
        self.assertEqual(sheet.spell_slots.get_current(1), 4)

    def test_sheet_short_rest_restores_warlock_slots(self) -> None:
        sheet = CharacterSheet(name="Hex", char_class="Warlock", level=5)
        sheet.spell_slots.apply_table(slots_table_for_class("Warlock", 5))  # type: ignore[arg-type]
        sheet.spell_slots.use(3, 1)
        sheet.short_rest(dice_spent=0, healing=0)
        self.assertEqual(sheet.spell_slots.get_current(3), 2)

    def test_lowest_available_upcasts(self) -> None:
        slots = SpellSlots.from_dict({"maximum": {"3": 2}, "current": {"3": 2}})
        self.assertEqual(slots.lowest_available(1), 3)
        self.assertIsNone(slots.lowest_available(4))
        slots.use(3)
        self.assertEqual(slots.lowest_available(1), 3)
        slots.use(3)
        self.assertIsNone(slots.lowest_available(1))

    def test_sheet_serialization_keeps_slots(self) -> None:
        sheet = CharacterSheet(name="Lyra", char_class="Cleric", level=3)
        sheet.spell_slots.set_level(1, 4, 2)
        sheet.spell_slots.set_level(2, 2)
        restored = CharacterSheet.from_dict(sheet.to_dict())
        self.assertEqual(restored.spell_slots.get_current(1), 2)
        self.assertEqual(restored.spell_slots.get_maximum(2), 2)


if __name__ == "__main__":
    unittest.main()
