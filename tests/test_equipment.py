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
        from sheets.containers import STORED_HANDS, STORED_LOOSE

        equipment = Equipment()
        equipment.add_item(
            slug=custom_slug("Dagger"), name="Dagger", kind=ITEM_KIND_CUSTOM, quantity=1
        )
        equipment.equip("Dagger")
        equipment.add_item(
            slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON, quantity=2
        )
        held = next(item for item in equipment.items if item.stored_in == STORED_HANDS)
        self.assertEqual(held.slug, "dagger")
        self.assertEqual(held.kind, ITEM_KIND_WEAPON)
        self.assertTrue(held.equipped)
        self.assertEqual(sum(item.quantity for item in equipment.items), 3)
        self.assertEqual(held.quantity, 2)
        leftover = next(
            item for item in equipment.items if item.stored_in == STORED_LOOSE
        )
        self.assertEqual(leftover.quantity, 1)

    def test_format_summary_can_exclude_equipped(self) -> None:
        equipment = Equipment()
        equipment.add_item(
            slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON, quantity=1
        )
        equipment.equip("Dagger")
        equipment.add_item(slug="rope", name="Rope", kind="item", quantity=1)
        summary = equipment.format_summary(exclude_equipped=True)
        self.assertIn("Rope", summary)
        self.assertNotIn("Dagger", summary)

    def test_parse_name_and_quantity(self) -> None:
        self.assertEqual(parse_name_and_quantity("dagger 2"), ("dagger", 2))
        self.assertEqual(parse_name_and_quantity("rope x50"), ("rope", 50))
        self.assertEqual(parse_name_and_quantity("room 101"), ("room 101", None))
        self.assertEqual(
            parse_name_and_quantity("long sword 2"), ("long sword 2", None)
        )

    def test_parse_name_quantity_and_weight(self) -> None:
        from sheets.equipment import parse_name_quantity_and_weight

        self.assertEqual(
            parse_name_quantity_and_weight("amulette 2lb"),
            ("amulette", None, 2.0),
        )
        self.assertEqual(
            parse_name_quantity_and_weight("amulette 2kg"),
            ("amulette", None, 4.0),
        )
        self.assertEqual(
            parse_name_quantity_and_weight("rope x50 10 lb"),
            ("rope", 50, 10.0),
        )
        self.assertEqual(
            parse_name_quantity_and_weight("dagger 2"),
            ("dagger", 2, None),
        )

    def test_parse_item_and_weight(self) -> None:
        from sheets.equipment import parse_item_and_weight

        self.assertEqual(parse_item_and_weight("Amulette 3"), ("Amulette", 6.0))
        self.assertEqual(parse_item_and_weight("Amulette 2.5lb"), ("Amulette", 2.5))
        self.assertEqual(parse_item_and_weight("Amulette 2kg"), ("Amulette", 4.0))

    def test_format_pounds_uses_kilograms(self) -> None:
        from sheets.equipment import format_pounds

        self.assertEqual(format_pounds(2), "1 kg")
        self.assertEqual(format_pounds(30), "15 kg")
        self.assertEqual(format_pounds(150), "75 kg")

    def test_stored_weight_totals(self) -> None:
        equipment = Equipment()
        equipment.add_item(
            slug="anvil", name="Anvil", kind="item", quantity=2, weight_lb=100
        )
        equipment.add_item(
            slug="feather", name="Feather", kind="item", quantity=1, weight_lb=0
        )
        self.assertEqual(equipment.total_weight_lb(), 200)

    def test_round_trip_keeps_weight(self) -> None:
        equipment = Equipment(
            items=[
                InventoryItem(slug="anvil", name="Anvil", kind="item", weight_lb=100)
            ]
        )
        restored = Equipment.from_dict(equipment.to_dict())
        self.assertEqual(restored.items[0].weight_lb, 100)

    def test_carrying_capacity_and_overload(self) -> None:
        from sheets.currency import Currency

        sheet = CharacterSheet(
            name="Hero",
            abilities={
                "str": 10,
                "dex": 10,
                "con": 10,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
        )
        self.assertEqual(sheet.carrying_capacity_lb(), 150)
        self.assertFalse(sheet.is_overloaded())
        sheet.equipment.add_item(
            slug="anvil", name="Anvil", kind="item", quantity=1, weight_lb=151
        )
        self.assertTrue(sheet.is_overloaded())
        sheet.equipment.remove_item("Anvil")
        sheet.currency = Currency(gp=50)
        self.assertEqual(sheet.currency.weight_lb(), 1)
        self.assertIn("coins", sheet.format_load())

    def test_encumbrance_slows_speed_but_does_not_stop(self) -> None:
        from sheets.equipment import encumbered_speed

        sheet = CharacterSheet(
            name="Hero",
            speed=30,
            abilities={
                "str": 10,
                "dex": 10,
                "con": 10,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
        )
        self.assertEqual(sheet.effective_speed(), 30)

        sheet.equipment.add_item(
            slug="anvil", name="Anvil", kind="item", quantity=1, weight_lb=300
        )
        self.assertTrue(sheet.is_overloaded())
        self.assertEqual(sheet.effective_speed(), 15)
        self.assertIn("15 ft.", sheet.format_speed())
        self.assertIn("−15", sheet.format_load())

        self.assertEqual(
            encumbered_speed(base_speed=30, carried_lb=1500, capacity_lb=150),
            5,
        )
        self.assertEqual(
            encumbered_speed(base_speed=30, carried_lb=150, capacity_lb=150),
            30,
        )

    def test_index_lookup_fills_missing_weight(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON)
        self.assertGreater(equipment.total_weight_lb(), 0)

    def test_items_go_in_backpack_or_hands(self) -> None:
        from sheets.containers import STORED_HANDS, STORED_LOOSE, STORED_WORN

        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item")
        equipment.add_item(slug="rope", name="Rope", kind="item", weight_lb=10)
        backpack = equipment.find_item("Backpack")
        rope = equipment.find_item("Rope")
        assert backpack is not None and rope is not None
        self.assertEqual(backpack.stored_in, STORED_WORN)
        self.assertEqual(rope.stored_in, "backpack")

        equipment.add_item(slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON)
        sword = equipment.find_item("Long Sword")
        assert sword is not None
        self.assertEqual(sword.stored_in, "backpack")

        empty = Equipment()
        empty.add_item(slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON)
        held = empty.find_item("Long Sword")
        assert held is not None
        self.assertEqual(held.stored_in, STORED_HANDS)

        empty.add_item(slug="anvil", name="Anvil", kind="item", weight_lb=100)
        anvil = empty.find_item("Anvil")
        assert anvil is not None
        self.assertEqual(anvil.stored_in, STORED_LOOSE)

    def test_add_puts_new_quantity_in_bag_not_hands(self) -> None:
        from sheets.containers import STORED_HANDS

        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item")
        equipment.add_item(slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON)
        equipment.hold("Dagger")
        held = next(item for item in equipment.items if item.stored_in == STORED_HANDS)
        self.assertEqual(held.quantity, 1)

        added = equipment.add_item(
            slug="dagger", name="Dagger", kind=ITEM_KIND_WEAPON, quantity=2
        )
        self.assertEqual(added.stored_in, "backpack")
        self.assertEqual(added.quantity, 2)
        held = next(item for item in equipment.items if item.stored_in == STORED_HANDS)
        self.assertEqual(held.quantity, 1)

    def test_adding_a_bag_packs_loose_items(self) -> None:
        from sheets.containers import STORED_LOOSE, STORED_WORN

        equipment = Equipment()
        equipment.add_item(slug="torch", name="Torch", kind="item", weight_lb=1)
        torch = equipment.find_item("Torch")
        assert torch is not None
        self.assertEqual(torch.stored_in, STORED_LOOSE)

        backpack = equipment.add_item(slug="backpack", name="Backpack", kind="item")
        self.assertEqual(backpack.stored_in, STORED_WORN)
        torch = equipment.find_item("Torch")
        assert torch is not None
        self.assertEqual(torch.stored_in, "backpack")

    def test_stow_adds_backpack_when_missing(self) -> None:
        from sheets.containers import STORED_LOOSE, STORED_WORN

        equipment = Equipment()
        equipment.add_item(slug="torch", name="Torch", kind="item", weight_lb=1)
        equipment.add_item(
            slug="leather-armor",
            name="Leather Armor",
            kind=ITEM_KIND_ARMOR,
            weight_lb=10,
        )
        torch = equipment.find_item("Torch")
        armor = equipment.find_item("Leather Armor")
        assert torch is not None and armor is not None
        self.assertEqual(torch.stored_in, STORED_LOOSE)
        self.assertEqual(armor.stored_in, STORED_LOOSE)

        worn = equipment.wear_loose_armor()
        bag = equipment.ensure_pack_bag()
        assert worn is not None and bag is not None
        self.assertEqual(worn.name, "Leather Armor")
        self.assertTrue(worn.equipped)
        self.assertEqual(worn.stored_in, STORED_WORN)
        self.assertEqual(bag.stored_in, STORED_WORN)
        torch = equipment.find_item("Torch")
        assert torch is not None
        self.assertEqual(torch.stored_in, "backpack")

    def test_pack_bundle_contents_requires_a_bag(self) -> None:
        from sheets.equipment import pack_bundle_contents

        self.assertIsNone(
            pack_bundle_contents(
                {"packContents": [{"item": "arrow|xphb", "quantity": 20}]}
            )
        )
        pieces = pack_bundle_contents(
            {
                "packContents": [
                    "backpack|xphb",
                    "bedroll|xphb",
                    {"item": "torch|xphb", "quantity": 10},
                ]
            }
        )
        self.assertEqual(
            pieces,
            [("backpack", 1), ("bedroll", 1), ("torch", 10)],
        )

    def test_put_and_hold(self) -> None:
        from sheets.containers import STORED_HANDS, parse_put_args

        self.assertEqual(parse_put_args("rope in backpack"), ("rope", "backpack"))
        self.assertEqual(parse_put_args("all in backpack"), ("all", "backpack"))
        self.assertEqual(parse_put_args("all backpack"), ("all", "backpack"))
        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item")
        equipment.add_item(slug="rope", name="Rope", kind="item", weight_lb=10)
        equipment.hold("Rope")
        rope = equipment.find_item("Rope")
        assert rope is not None
        self.assertEqual(rope.stored_in, STORED_HANDS)
        equipment.put_in("Rope", "Backpack")
        stored = equipment.find_item("Rope")
        assert stored is not None
        self.assertEqual(stored.stored_in, "backpack")

    def test_same_place_stacks_merge(self) -> None:
        from sheets.containers import STORED_HANDS, STORED_LOOSE
        from sheets.equipment import InventoryItem

        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item")
        equipment.add_item(
            slug="torch", name="Torch", kind="item", quantity=2, weight_lb=1
        )
        equipment.add_item(
            slug="torch",
            name="Torch",
            kind="item",
            quantity=3,
            weight_lb=1,
            stored_in=STORED_LOOSE,
            auto_stow=False,
        )
        equipment.stow_loose()
        in_bag = [item for item in equipment.items if item.stored_in == "backpack"]
        self.assertEqual(len(in_bag), 1)
        self.assertEqual(in_bag[0].quantity, 5)

        equipment.hold("Torch")
        equipment.items.append(
            InventoryItem(
                slug="torch",
                name="Torch",
                kind="item",
                quantity=1,
                stored_in=STORED_HANDS,
                equipped=True,
                weight_lb=1,
            )
        )
        equipment.coalesce_stacks()
        held = [item for item in equipment.items if item.stored_in == STORED_HANDS]
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0].quantity, 2)

    def test_put_moves_every_stack_and_all_gear(self) -> None:
        from sheets.containers import STORED_HANDS, STORED_LOOSE

        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item")
        equipment.add_item(
            slug="torch", name="Torch", kind="item", quantity=2, weight_lb=1
        )
        equipment.hold("Torch")
        equipment.add_item(
            slug="torch",
            name="Torch",
            kind="item",
            quantity=3,
            weight_lb=1,
            stored_in=STORED_LOOSE,
            auto_stow=False,
        )
        stacked = equipment.put_in("Torch", "backpack")
        self.assertEqual(stacked.stored_in, "backpack")
        self.assertEqual(stacked.quantity, 5)
        self.assertFalse(
            any(
                item.stored_in == STORED_HANDS
                for item in equipment.items
                if item.name == "Torch"
            )
        )

        equipment.add_item(slug="bedroll", name="Bedroll", kind="item", weight_lb=7)
        equipment.add_item(
            slug="kit",
            name="Herbalism Kit",
            kind="item",
            weight_lb=3,
            stored_in=STORED_LOOSE,
            auto_stow=False,
        )
        equipment.put_in("all", "backpack")
        self.assertFalse(
            any(item.stored_in == STORED_LOOSE for item in equipment.items)
        )
        self.assertEqual(equipment.find_item("Bedroll").stored_in, "backpack")
        self.assertEqual(equipment.find_item("Herbalism Kit").stored_in, "backpack")

    def test_put_on_belt(self) -> None:
        from sheets.containers import BELT_SLOTS, STORED_BELT, STORED_LOOSE, STORED_WORN

        equipment = Equipment()
        equipment.add_item(
            slug=custom_slug("Potion"), name="Potion", kind=ITEM_KIND_CUSTOM, quantity=5
        )
        equipment.put_in("Potion", "ceinture")
        on_belt = [item for item in equipment.items if item.stored_in == STORED_BELT]
        leftover = [item for item in equipment.items if item.stored_in == STORED_LOOSE]
        self.assertEqual(len(on_belt), 1)
        self.assertEqual(on_belt[0].quantity, BELT_SLOTS)
        self.assertEqual(leftover[0].quantity, 1)
        self.assertEqual(equipment.belt_slots_used(), BELT_SLOTS)

        equipment.stow_loose()
        on_belt = equipment.find_item("Potion")
        assert on_belt is not None
        self.assertEqual(on_belt.stored_in, STORED_BELT)

        equipment.add_item(
            slug=custom_slug("Torch"), name="Torch", kind=ITEM_KIND_CUSTOM
        )
        with self.assertRaises(ValueError):
            equipment.hang_on_belt("Torch")

        bulky = Equipment()
        bulky.add_item(slug="backpack", name="Backpack", kind="item")
        with self.assertRaises(ValueError):
            bulky.hang_on_belt("Backpack")

        armor = Equipment()
        armor.add_item(slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR)
        with self.assertRaises(ValueError):
            armor.hang_on_belt("Leather Armor")

        pouch = Equipment()
        pouch.add_item(slug="pouch", name="Pouch", kind="item")
        pouch.hang_on_belt("Pouch")
        hung = pouch.find_item("Pouch")
        assert hung is not None
        self.assertEqual(hung.stored_in, STORED_BELT)
        name, value = pouch.format_belt_field()
        self.assertEqual(name, "🪢 Belt (1/4)")
        self.assertIn("Pouch", value)

        custom_bag = Equipment()
        custom_bag.add_item(
            slug=custom_slug("Petite sacoche"),
            name="Petite sacoche",
            kind=ITEM_KIND_CUSTOM,
        )
        custom_bag.hang_on_belt("Petite sacoche")
        custom_bag.mark_as_bag("Petite sacoche")
        marked = custom_bag.find_item("Petite sacoche")
        assert marked is not None
        self.assertEqual(marked.stored_in, STORED_WORN)

        bourse = Equipment()
        bourse.add_item(
            slug=custom_slug("Bourse"), name="Bourse", kind=ITEM_KIND_CUSTOM
        )
        bourse.hang_on_belt("Bourse")
        bourse.mark_as_bag("Bourse", 6)
        marked_bourse = bourse.find_item("Bourse")
        assert marked_bourse is not None
        self.assertEqual(marked_bourse.stored_in, STORED_BELT)

    def test_custom_item_can_be_marked_as_bag(self) -> None:
        from sheets.containers import DEFAULT_BAG_CAPACITY_LB, STORED_LOOSE, STORED_WORN

        equipment = Equipment()
        equipment.add_item(
            slug=custom_slug("Coffre"),
            name="Coffre",
            kind=ITEM_KIND_CUSTOM,
            weight_lb=25,
        )
        chest = equipment.find_item("Coffre")
        assert chest is not None
        self.assertFalse(equipment.is_container(chest))
        self.assertEqual(chest.stored_in, STORED_LOOSE)

        equipment.mark_as_bag("Coffre")
        chest = equipment.find_item("Coffre")
        assert chest is not None
        self.assertTrue(equipment.is_container(chest))
        self.assertEqual(chest.capacity_lb, DEFAULT_BAG_CAPACITY_LB)
        self.assertEqual(chest.stored_in, STORED_WORN)

        equipment.add_item(
            slug=custom_slug("Torch"), name="Torch", kind=ITEM_KIND_CUSTOM, weight_lb=1
        )
        equipment.put_in("Torch", "Coffre")
        torch = equipment.find_item("Torch")
        assert torch is not None
        self.assertEqual(torch.stored_in, chest.slug)

        restored = Equipment.from_dict(equipment.to_dict())
        restored_chest = restored.find_item("Coffre")
        assert restored_chest is not None
        self.assertEqual(restored_chest.capacity_lb, DEFAULT_BAG_CAPACITY_LB)
        self.assertTrue(restored.is_container(restored_chest))

        equipment.mark_as_bag("Coffre", 50)
        chest = equipment.find_item("Coffre")
        assert chest is not None
        self.assertEqual(chest.capacity_lb, 50)

        equipment.mark_as_bag("Coffre", 0)
        chest = equipment.find_item("Coffre")
        torch = equipment.find_item("Torch")
        assert chest is not None and torch is not None
        self.assertIsNone(chest.capacity_lb)
        self.assertFalse(equipment.is_container(chest))
        self.assertNotEqual(torch.stored_in, chest.slug)

        official = Equipment()
        official.add_item(slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON)
        with self.assertRaises(ValueError):
            official.mark_as_bag("Long Sword")

    def test_bag_of_holding_contents_are_weightless(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="bag-of-holding", name="Bag of Holding", kind="item")
        equipment.add_item(slug="anvil", name="Anvil", kind="item", weight_lb=400)
        self.assertLess(equipment.carried_weight_lb(), 50)
        self.assertGreater(equipment.total_weight_lb(), 400)

    def test_equip_armor_replaces_previous(self) -> None:
        equipment = Equipment()
        equipment.add_item(
            slug="leather-armor", name="Leather Armor", kind=ITEM_KIND_ARMOR
        )
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

    def test_gear_embed_chunks_long_fields(self) -> None:
        from sheets.commands.equipment import _chunk_field_value

        lines = [f"item-{index} " + ("x" * 80) for index in range(30)]
        chunks = _chunk_field_value("\n".join(lines))
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1024)

    def test_custom_slug(self) -> None:
        self.assertTrue(custom_slug("Healing Potion").startswith("custom:"))

    def test_format_item_line_links_indexed_gear(self) -> None:
        item = InventoryItem(
            slug="long-sword", name="Long Sword", kind=ITEM_KIND_WEAPON
        )
        line = format_item_line(item)
        self.assertIn("[Long Sword](https://5e.tools/items.html#", line)
        self.assertIn("long", line.lower())
        self.assertNotIn("open5e.com", line)

    def test_format_item_line_custom_has_no_link(self) -> None:
        item = InventoryItem(
            slug=custom_slug("Potion"), name="Potion", kind=ITEM_KIND_CUSTOM
        )
        line = format_item_line(item)
        self.assertEqual(line, "Potion")
        self.assertNotIn("**", line)
        self.assertNotIn("open5e.com", line)


if __name__ == "__main__":
    unittest.main()
