import unittest

from sheets.data import CharacterSheet
from sheets.equipment import (
    ITEM_KIND_ARMOR,
    ITEM_KIND_CUSTOM,
    ITEM_KIND_WEAPON,
    Equipment,
    InventoryItem,
    custom_slug,
    format_item_line,
    parse_name_and_quantity,
)


class TestEquipment(unittest.TestCase):
    def test_round_trip_dict(self) -> None:
        equipment = Equipment(
            items=[
                InventoryItem(
                    slug="longsword",
                    name="Longsword",
                    kind=ITEM_KIND_WEAPON,
                    equipped=True,
                ),
                InventoryItem(
                    slug="chain-mail",
                    name="Chain Mail",
                    kind=ITEM_KIND_ARMOR,
                    equipped=True,
                ),
            ]
        )
        restored = Equipment.from_dict(equipment.to_dict())
        self.assertEqual(len(restored.items), 2)
        self.assertTrue(restored.items[0].equipped)

    def test_character_sheet_backward_compatible(self) -> None:
        sheet = CharacterSheet.from_dict({"name": "Hero"})
        self.assertEqual(sheet.equipment.items, [])

    def test_add_stacks_same_slug(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="rope", name="Rope", kind="item", quantity=2)
        equipment.add_item(slug="rope", name="Rope", kind="item", quantity=3)
        self.assertEqual(len(equipment.items), 1)
        self.assertEqual(equipment.items[0].quantity, 5)

    def test_add_upgrades_custom_entry_with_same_name(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug=custom_slug("Dagger"), name="Dagger", kind=ITEM_KIND_CUSTOM, quantity=1)
        equipment.equip("Dagger")
        equipment.add_item(slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON, quantity=2)
        self.assertEqual(len(equipment.items), 1)
        item = equipment.items[0]
        self.assertEqual(item.slug, "dagger")
        self.assertEqual(item.kind, ITEM_KIND_WEAPON)
        self.assertEqual(item.quantity, 3)
        self.assertTrue(item.equipped)

    def test_format_summary_can_exclude_equipped(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON, quantity=1)
        equipment.equip("Dagger")
        equipment.add_item(slug="rope", name="Rope", kind="item", quantity=1)
        summary = equipment.format_summary(exclude_equipped=True)
        self.assertIn("Rope", summary)
        self.assertNotIn("Dagger", summary)

    def test_parse_name_and_quantity(self) -> None:
        self.assertEqual(parse_name_and_quantity("dagger 2"), ("dagger", 2))
        self.assertEqual(parse_name_and_quantity("rope x50"), ("rope", 50))
        self.assertEqual(parse_name_and_quantity("room 101"), ("room 101", None))
        self.assertEqual(parse_name_and_quantity("long sword 2"), ("long sword 2", None))

    def test_equip_armor_replaces_previous(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR)
        equipment.add_item(slug="chain-mail", name="Chain Mail", kind=ITEM_KIND_ARMOR)
        equipment.equip("Leather Armor")
        equipment.equip("Chain Mail")
        leather = equipment.find_item("Leather Armor")
        chain = equipment.find_item("Chain Mail")
        assert leather is not None and chain is not None
        self.assertFalse(leather.equipped)
        self.assertTrue(chain.equipped)

    def test_remove_partial_quantity(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="arrow", name="Arrow", kind="item", quantity=10)
        removed = equipment.remove_item("Arrow", quantity=4)
        assert removed is not None
        self.assertEqual(removed.quantity, 4)
        item = equipment.find_item("Arrow")
        assert item is not None
        self.assertEqual(item.quantity, 6)

    def test_custom_slug(self) -> None:
        self.assertTrue(custom_slug("Healing Potion").startswith("custom:"))

    def test_format_item_line_links_indexed_gear(self) -> None:
        item = InventoryItem(slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON)
        line = format_item_line(item)
        self.assertIn("[Long Sword](https://5e.tools/items.html#", line)
        self.assertIn("long", line.lower())
        self.assertNotIn("open5e.com", line)

    def test_format_item_line_custom_has_no_link(self) -> None:
        item = InventoryItem(slug=custom_slug("Potion"), name="Potion", kind=ITEM_KIND_CUSTOM)
        line = format_item_line(item)
        self.assertIn("**Potion**", line)
        self.assertNotIn("open5e.com", line)


if __name__ == "__main__":
    unittest.main()
