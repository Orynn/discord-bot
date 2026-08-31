import unittest
from unittest.mock import AsyncMock, patch

from sheets.data import CharacterSheet
from sheets.ddb_pdf import (
    collect_equipment_entries,
    collect_equipped_names,
    extract_ddb_fields,
    fill_sheet_equipment,
    parse_ddb_pdf,
    parse_equipment_entry,
    _parse_class_and_level,
)
from sheets.equipment import (
    ITEM_KIND_ARMOR,
    ITEM_KIND_CUSTOM,
    ITEM_KIND_ITEM,
    ITEM_KIND_WEAPON,
)
from sheets.containers import STORED_HANDS, STORED_WORN


class TestDdbPdf(unittest.TestCase):
    def test_rejects_non_pdf_bytes(self) -> None:
        with self.assertRaises(ValueError):
            parse_ddb_pdf(b"not a pdf")

    def test_extract_fields_from_pdf_bytes(self) -> None:
        sample = (
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Magnus)"
            b"/T(CLASS  LEVEL)/V(Cleric 8)"
            b"/T(STR)/V(17)"
            b"/T(GP)/V(160)"
        )
        fields = extract_ddb_fields(sample)
        self.assertEqual(fields["CharacterName"], "Magnus")
        self.assertEqual(fields["CLASS  LEVEL"], "Cleric 8")
        self.assertEqual(fields["STR"], "17")
        self.assertEqual(fields["GP"], "160")

    def test_extract_equipment_keeps_parentheses(self) -> None:
        sample = (
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Fox)"
            b"/T(Equipment)/V(Leather Armor, Longsword, Backpack, Rations \\(10\\))"
            b"/T(Wpn Name)/V(Longsword)"
        )
        fields = extract_ddb_fields(sample)
        self.assertEqual(
            fields["Equipment"],
            "Leather Armor, Longsword, Backpack, Rations (10)",
        )
        self.assertEqual(fields["Wpn Name"], "Longsword")

    def test_parse_class_and_level_with_subclass(self) -> None:
        char_class, level, subclass = _parse_class_and_level("Cleric 8 (Life Domain)")
        self.assertEqual(char_class, "Cleric")
        self.assertEqual(level, 8)
        self.assertEqual(subclass, "Life Domain")

    def test_parse_class_without_subclass(self) -> None:
        char_class, level, subclass = _parse_class_and_level("Fighter 3")
        self.assertEqual(char_class, "Fighter")
        self.assertEqual(level, 3)
        self.assertEqual(subclass, "")

    def test_parse_equipment_entry_quantities(self) -> None:
        self.assertEqual(parse_equipment_entry("Rations (10)"), ("Rations", 10))
        self.assertEqual(parse_equipment_entry("Arrows x20"), ("Arrows", 20))
        self.assertEqual(parse_equipment_entry("2 Daggers"), ("Daggers", 2))
        self.assertEqual(
            parse_equipment_entry("Potion of Healing (Greater)"),
            ("Potion of Healing (Greater)", 1),
        )
        self.assertEqual(parse_equipment_entry("10-foot pole"), ("10-foot pole", 1))
        self.assertIsNone(parse_equipment_entry("160 gp"))

    def test_collect_equipment_from_comma_and_weapon_fields(self) -> None:
        fields = {
            "Equipment": "Leather Armor, Longsword, Backpack, Rations (10)",
            "Treasure": "Potion of Healing x2",
            "Wpn Name": "Longsword",
            "Wpn Name 2": "Dagger",
        }
        entries = collect_equipment_entries(fields)
        by_name = dict(entries)
        self.assertEqual(by_name["Leather Armor"], 1)
        self.assertEqual(by_name["Rations"], 10)
        self.assertEqual(by_name["Potion of Healing"], 2)
        self.assertEqual(collect_equipped_names(fields), ["Longsword", "Dagger"])

    def test_parse_pdf_includes_equipment_entries(self) -> None:
        sample = (
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Fox)"
            b"/T(CLASS  LEVEL)/V(Fighter 3)"
            b"/T(Equipment)/V(Longsword, Shield, Backpack)"
            b"/T(Wpn Name)/V(Longsword)"
        )
        imported = parse_ddb_pdf(sample)
        self.assertEqual(
            dict(imported.equipment_entries),
            {"Longsword": 1, "Shield": 1, "Backpack": 1},
        )
        self.assertEqual(imported.equipped_names, ["Longsword"])


class TestFillSheetEquipment(unittest.IsolatedAsyncioTestCase):
    async def test_looks_up_5etools_and_stows_gear(self) -> None:
        sheet = CharacterSheet(name="Fox")
        catalog = {
            "backpack": {
                "slug": "backpack",
                "name": "Backpack",
                "kind": ITEM_KIND_ITEM,
                "weight_lb": 5,
            },
            "longsword": {
                "slug": "longsword",
                "name": "Longsword",
                "kind": ITEM_KIND_WEAPON,
                "weight_lb": 3,
            },
            "leather armor": {
                "slug": "leather-armor",
                "name": "Leather Armor",
                "kind": ITEM_KIND_ARMOR,
                "weight_lb": 10,
            },
            "rations": {
                "slug": "rations",
                "name": "Rations",
                "kind": ITEM_KIND_ITEM,
                "weight_lb": 0.5,
            },
        }

        async def _search(query: str) -> dict:
            entry = catalog.get(query.lower())
            if entry is None:
                from srd.fivetools import Open5eNotFoundError

                raise Open5eNotFoundError(query)
            return entry

        with patch(
            "srd.fivetools.search_equipment", new=AsyncMock(side_effect=_search)
        ):
            with patch("srd.fivetools.register_glossary_item"):
                matched, custom = await fill_sheet_equipment(
                    sheet,
                    entries=[
                        ("Leather Armor", 1),
                        ("Longsword", 1),
                        ("Backpack", 1),
                        ("Rations", 10),
                        ("Lucky Charm", 1),
                    ],
                    equipped_names=["Longsword"],
                )

        self.assertEqual(matched, 4)
        self.assertEqual(custom, 1)
        backpack = sheet.equipment.find_item("Backpack")
        rations = sheet.equipment.find_item("Rations")
        sword = sheet.equipment.find_item("Longsword")
        armor = sheet.equipment.find_item("Leather Armor")
        charm = sheet.equipment.find_item("Lucky Charm")
        assert backpack and rations and sword and armor and charm
        self.assertEqual(rations.quantity, 10)
        self.assertEqual(rations.stored_in, "backpack")
        self.assertEqual(armor.stored_in, STORED_WORN)
        self.assertTrue(armor.equipped)
        self.assertEqual(sword.stored_in, STORED_HANDS)
        self.assertTrue(sword.equipped)
        self.assertEqual(charm.kind, ITEM_KIND_CUSTOM)
        self.assertEqual(backpack.stored_in, STORED_WORN)

    async def test_unpacks_explorers_pack_into_backpack(self) -> None:
        from srd.fivetools.loader import reload_index
        from sheets.ddb_pdf import add_catalog_equipment
        from srd import fivetools

        reload_index()
        sheet = CharacterSheet(name="Ilidor")
        pack = await fivetools.search_equipment("Explorer's Pack")
        _matched, _custom, names = await add_catalog_equipment(sheet, pack, 1)
        self.assertIn("Backpack", names)
        self.assertIn("Bedroll", names)
        backpack = sheet.equipment.find_item("Backpack")
        bedroll = sheet.equipment.find_item("Bedroll")
        assert backpack is not None and bedroll is not None
        self.assertTrue(sheet.equipment.is_container(backpack))
        self.assertEqual(bedroll.stored_in, "backpack")


if __name__ == "__main__":
    unittest.main()
