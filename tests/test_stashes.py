import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord

import data.db as db_module
from sheets.containers import STORED_WORN
from sheets.equipment import Equipment, InventoryItem
from sheets.stashes import (
    PlaceStash,
    get_stash,
    infer_place_from_channel,
    list_stashes,
    parse_let_args,
    save_stash,
)


class TestParseLetArgs(unittest.TestCase):
    def test_item_place_and_note(self) -> None:
        args = parse_let_args("torch 2 at Padhiver -- sous le lit")
        self.assertFalse(args.list_only)
        self.assertEqual(args.item, "torch")
        self.assertEqual(args.quantity, 2)
        self.assertEqual(args.place, "Padhiver")
        self.assertEqual(args.note, "sous le lit")

    def test_french_at_and_empty_list(self) -> None:
        args = parse_let_args("à l'auberge")
        self.assertTrue(args.list_only)
        self.assertEqual(args.place, "l'auberge")
        self.assertEqual(args.item, "")

        empty = parse_let_args("")
        self.assertTrue(empty.list_only)
        self.assertTrue(parse_let_args("places").all_places)

    def test_item_only(self) -> None:
        args = parse_let_args("Rope")
        self.assertEqual(args.item, "Rope")
        self.assertIsNone(args.place)
        self.assertEqual(args.note, "")


class TestInferPlace(unittest.TestCase):
    def test_thread_name(self) -> None:
        channel = SimpleNamespace(type=discord.ChannelType.public_thread, name="Padhiver")
        self.assertEqual(infer_place_from_channel(channel), "Padhiver")

    def test_text_channel_is_not_a_place(self) -> None:
        channel = SimpleNamespace(type=discord.ChannelType.text, name="ilidor-rp")
        self.assertIsNone(infer_place_from_channel(channel))


class TestDetachAndRestore(unittest.TestCase):
    def test_leaves_bag_with_contents(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="backpack", name="Backpack", kind="item", weight_lb=5)
        equipment.add_item(slug="rope", name="Rope", kind="item", quantity=1, stored_in="backpack", auto_stow=False)
        equipment.add_item(slug="torch", name="Torch", kind="item", quantity=3, stored_in="backpack", auto_stow=False)

        detached = equipment.detach_for_stash("backpack")
        self.assertEqual([item.name for item in detached], ["Backpack", "Rope", "Torch"])
        self.assertEqual(equipment.items, [])
        self.assertIsNone(detached[0].stored_in)
        self.assertEqual(detached[2].stored_in, "backpack")

    def test_leaves_partial_stack(self) -> None:
        equipment = Equipment()
        equipment.add_item(slug="torch", name="Torch", kind="item", quantity=5, auto_stow=False)
        detached = equipment.detach_for_stash("torch", quantity=2)
        self.assertEqual(detached[0].quantity, 2)
        self.assertEqual(equipment.find_item("torch").quantity, 3)

    def test_restore_keeps_bag_contents(self) -> None:
        source = Equipment()
        source.add_item(slug="backpack", name="Backpack", kind="item", weight_lb=5)
        source.add_item(slug="rope", name="Rope", kind="item", stored_in="backpack", auto_stow=False)
        detached = source.detach_for_stash("backpack")

        dest = Equipment()
        dest.add_item(slug="torch", name="Torch", kind="item", stored_in="loose", auto_stow=False)
        dest.restore_stash_items(detached)

        bag = dest.find_item("backpack")
        rope = dest.find_item("rope")
        torch = dest.find_item("torch")
        self.assertEqual(bag.stored_in, STORED_WORN)
        self.assertEqual(rope.stored_in, "backpack")
        self.assertEqual(torch.stored_in, "loose")


class TestStashStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_round_trip_and_stack(self) -> None:
        stash = PlaceStash(guild_id=1, place_key="padhiver", place_name="Padhiver")
        torch = InventoryItem(slug="torch", name="Torch", kind="item", quantity=2)
        stash.add_entries([torch], note="sous le lit", left_by="Ilidor")
        stash.add_entries(
            [InventoryItem(slug="torch", name="Torch", kind="item", quantity=1)],
            note="sous le lit",
            left_by="Ilidor",
        )
        save_stash(stash)

        loaded = get_stash(guild_id=1, place="PADHIVER")
        self.assertEqual(loaded.place_name, "Padhiver")
        self.assertEqual(loaded.entries[0].item.quantity, 3)
        self.assertIn("Ilidor", "\n".join(loaded.format_lines()))
        self.assertIn("sous le lit", "\n".join(loaded.format_lines()))

    def test_take_bag_and_empty_place(self) -> None:
        stash = get_stash(guild_id=1, place="Camp")
        bag = InventoryItem(slug="backpack", name="Backpack", kind="item")
        rope = InventoryItem(slug="rope", name="Rope", kind="item", stored_in="backpack")
        stash.add_entries([bag, rope], left_by="Ilidor")
        save_stash(stash)

        taken = stash.take_items("backpack")
        self.assertEqual([item.name for item in taken], ["Backpack", "Rope"])
        save_stash(stash)
        self.assertEqual(list_stashes(guild_id=1), [])

    def test_take_partial_quantity(self) -> None:
        stash = get_stash(guild_id=1, place="Camp")
        stash.add_entries([InventoryItem(slug="torch", name="Torch", quantity=5)], left_by="Ilidor")
        taken = stash.take_items("torch", quantity=2)
        self.assertEqual(taken[0].quantity, 2)
        self.assertEqual(stash.entries[0].item.quantity, 3)


if __name__ == "__main__":
    unittest.main()
