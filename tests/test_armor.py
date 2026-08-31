import unittest

from sheets.armor import apply_armor_ac, computed_ac, format_ac_field
from sheets.data import CharacterSheet
from sheets.equipment import (
    ITEM_KIND_ARMOR,
    ITEM_KIND_CUSTOM,
    ITEM_KIND_WEAPON,
    custom_slug,
)


class TestArmorClass(unittest.TestCase):
    def _sheet(self, **abilities: int) -> CharacterSheet:
        sheet = CharacterSheet(name="Hero", ac=10)
        for ability, score in abilities.items():
            sheet.abilities[ability] = score
        return sheet

    def test_leather_adds_full_dex(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.equipment.add_item(
            slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.equip("Leather Armor")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 14)
        self.assertIn("Leather Armor", format_ac_field(sheet))

    def test_medium_armor_caps_dex_at_two(self) -> None:
        sheet = self._sheet(dex=18)
        sheet.equipment.add_item(
            slug="breastplate", name="Breastplate", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.equip("Breastplate")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 16)

    def test_heavy_armor_ignores_dex(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.equipment.add_item(
            slug="chain-mail", name="Chain Mail", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.equip("Chain Mail")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 16)

    def test_shield_adds_two(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.equipment.add_item(
            slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.add_item(slug="shield", name="Shield", kind=ITEM_KIND_ARMOR)
        sheet.equipment.equip("Leather Armor")
        sheet.equipment.equip("Shield")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 16)

    def test_unequip_returns_to_unarmored(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.equipment.add_item(
            slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.equip("Leather Armor")
        apply_armor_ac(sheet)
        sheet.equipment.unequip("Leather Armor")
        apply_armor_ac(sheet, force=True)
        self.assertEqual(sheet.ac, 13)

    def test_barbarian_unarmored_defense(self) -> None:
        sheet = self._sheet(dex=16, con=14)
        sheet.char_class = "Barbarian"
        apply_armor_ac(sheet, force=True)
        self.assertEqual(sheet.ac, 15)

    def test_monk_unarmored_defense_without_shield(self) -> None:
        sheet = self._sheet(dex=16, wis=14)
        sheet.char_class = "Monk"
        apply_armor_ac(sheet, force=True)
        self.assertEqual(sheet.ac, 15)

    def test_custom_armor_keeps_manual_ac(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.ac = 17
        sheet.equipment.add_item(
            slug=custom_slug("Bone Armor"),
            name="Bone Armor",
            kind=ITEM_KIND_CUSTOM,
        )
        sheet.equipment.items[0].kind = ITEM_KIND_ARMOR
        sheet.equipment.equip("Bone Armor")
        self.assertIsNone(computed_ac(sheet))
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 17)

    def test_dex_change_updates_light_armor(self) -> None:
        sheet = self._sheet(dex=10)
        sheet.equipment.add_item(
            slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR
        )
        sheet.equipment.equip("Leather Armor")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 11)
        sheet.set_field("dex", "16")
        self.assertEqual(sheet.ac, 14)

    def test_unarmored_dex_change_does_not_overwrite(self) -> None:
        sheet = self._sheet(dex=10)
        sheet.ac = 13
        sheet.set_field("dex", "16")
        self.assertEqual(sheet.ac, 13)

    def test_equip_weapon_does_not_change_ac(self) -> None:
        sheet = self._sheet(dex=16)
        sheet.ac = 13
        sheet.equipment.add_item(slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON)
        sheet.equipment.equip("Dagger")
        apply_armor_ac(sheet)
        self.assertEqual(sheet.ac, 13)


if __name__ == "__main__":
    unittest.main()
