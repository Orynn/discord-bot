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

    def test_extracts_value_before_name(self) -> None:
        sample = (
            b"%PDF-1.4\n"
            b"<< /V (Magnus) /T (CharacterName) >>"
            b"<< /V (Leather Armor, Longsword) /T (Equipment) >>"
        )
        fields = extract_ddb_fields(sample)
        self.assertEqual(fields["CharacterName"], "Magnus")
        self.assertEqual(fields["Equipment"], "Leather Armor, Longsword")

    def test_extracts_hex_and_indirect_equipment(self) -> None:
        encoded = "Leather Armor, Backpack".encode("utf-16-be")
        hex_value = "FEFF" + encoded.hex().upper()
        sample = (
            b"%PDF-1.4\n"
            b"10 0 obj\n(Longsword, Shield)\nendobj\n"
            b"/T(CharacterName)/V(Fox)"
            b"/T(CLASS  LEVEL)/V(Fighter 3)"
            b"<< /T (Equipment) /V 10 0 R >>"
            b"<< /T (Treasure) /V <" + hex_value.encode("ascii") + b"> >>"
        )
        fields = extract_ddb_fields(sample)
        self.assertEqual(fields["Equipment"], "Longsword, Shield")
        self.assertEqual(fields["Treasure"], "Leather Armor, Backpack")
        imported = parse_ddb_pdf(
            b"%PDF-1.4\n"
            b"10 0 obj\n(Longsword, Shield, Backpack)\nendobj\n"
            b"/T(CharacterName)/V(Fox)"
            b"/T(CLASS  LEVEL)/V(Fighter 3)"
            b"<< /T (Equipment) /V 10 0 R >>"
        )
        self.assertEqual(
            dict(imported.equipment_entries),
            {"Longsword": 1, "Shield": 1, "Backpack": 1},
        )

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

    def test_collects_eq_name_table(self) -> None:
        fields = {
            "Eq Name0": "Chain Mail",
            "Eq Qty0": "1",
            "Eq Name1": "Javelin",
            "Eq Qty1": "6",
            "Eq Name2": "Rations",
            "Eq Qty2": "7",
            "Wpn Name": "Chill Touch",
            "Wpn Name 2": "Unarmed Strike",
            "spellName0": "Chill Touch",
        }
        self.assertEqual(
            dict(collect_equipment_entries(fields)),
            {"Chain Mail": 1, "Javelin": 6, "Rations": 7},
        )
        imported = parse_ddb_pdf(
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Sasmen)"
            b"/T(CLASS  LEVEL)/V(Paladin 1)"
            b"/T(Eq Name0)/V(Chain Mail)/T(Eq Qty0)/V(1)"
            b"/T(Eq Name1)/V(Longsword)/T(Eq Qty1)/V(1)"
            b"/T(Wpn Name)/V(Chill Touch)"
            b"/T(Wpn Name 2)/V(Unarmed Strike)"
            b"/T(spellName0)/V(Chill Touch)"
        )
        self.assertEqual(
            dict(imported.equipment_entries),
            {"Chain Mail": 1, "Longsword": 1},
        )
        self.assertEqual(imported.equipped_names, [])

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

    def test_placeholder_name_uses_player_name(self) -> None:
        imported = parse_ddb_pdf(
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(sasmen's Character)"
            b"/T(PLAYER NAME)/V(sasmen)"
            b"/T(CLASS  LEVEL)/V(Paladin 1)"
        )
        self.assertEqual(imported.sheet.name, "sasmen")

    def test_imports_notes_skills_saves_and_slots(self) -> None:
        imported = parse_ddb_pdf(
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Lyra)"
            b"/T(CLASS  LEVEL)/V(Wizard 5)"
            b"/T(RACE)/V(Elf)"
            b"/T(BACKGROUND)/V(Sage)"
            b"/T(STR)/V(10)/T(DEX)/V(14)/T(CON)/V(12)"
            b"/T(INT)/V(16)/T(WIS)/V(13)/T(CHA)/V(8)"
            b"/T(MaxHP)/V(32)"
            b"/T(AC)/V(12)"
            b"/T(Speed)/V(30 ft. (Walking))"
            b"/T(ALIGNMENT)/V(Chaotic Neutral)"
            b"/T(GENDER)/V(female)"
            b"/T(AGE)/V(120)"
            b"/T(HEIGHT)/V(180 cm)"
            b"/T(WEIGHT)/V(60)"
            b"/T(SIZE)/V(Medium)"
            b"/T(EYES)/V(green)"
            b"/T(SKIN)/V(pale)"
            b"/T(FAITH)/V(couronne aurifere)"
            b"/T(AdditionalSenses)/V(Darkvision 60 ft.)"
            b"/T(Defenses)/V(Resistances - Necrotic)"
            b"/T(AthleticsProf)/V(P)"
            b"/T(SleightofHandProf)/V(P)"
            b"/T(WisProf)/V(P)"
            b"/T(ST Wisdom)/V(+4)"
            b"/T(Inspiration)/V(P)"
            b"/T(ProficienciesLang)/V(=== ARMOR === \\nNone\\n\\n=== LANGUAGES === \\nCommon, Elvish)"
            b"/T(FeaturesTraits1)/V(* Darkvision\\n* Fiendish Legacy\\n* Size)"
            b"/T(Eq Name0)/V(Emblem)/T(Eq Qty0)/V(1)/T(Eq Weight0)/V(2 lb.)"
        )
        sheet = imported.sheet
        self.assertEqual(sheet.hp_current, 32)
        self.assertEqual(sheet.hp_max, 32)
        self.assertEqual(sheet.speed, 30)
        self.assertTrue(sheet.inspired)
        self.assertIn("athletics", sheet.skill_proficiencies)
        self.assertIn("sleight_of_hand", sheet.skill_proficiencies)
        self.assertIn("wis", sheet.save_proficiencies)
        self.assertEqual(sheet.spell_slots.get_maximum(1), 4)
        self.assertEqual(sheet.spell_slots.get_maximum(3), 2)
        self.assertIn("Chaotic Neutral", sheet.notes)
        self.assertIn("Foi : couronne aurifere", sheet.notes)
        self.assertIn("Sens : Darkvision 60 ft.", sheet.notes)
        self.assertIn("Défenses : Resistances - Necrotic", sheet.notes)
        self.assertIn("Langues : Common, Elvish", sheet.notes)
        self.assertIn("Darkvision", sheet.notes)
        self.assertIn("Fiendish Legacy", sheet.notes)
        self.assertNotIn("Traits : Size", sheet.notes)
        self.assertEqual(imported.equipment_weights.get("emblem"), 2.0)

    def test_infers_skill_proficiency_from_modifier(self) -> None:
        imported = parse_ddb_pdf(
            b"%PDF-1.4\n"
            b"/T(CharacterName)/V(Fox)"
            b"/T(CLASS  LEVEL)/V(Fighter 3)"
            b"/T(STR)/V(16)"
            b"/T(Athletics)/V(+5)"
        )
        self.assertIn("athletics", imported.sheet.skill_proficiencies)


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
                    weights={"lucky charm": 1.0},
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
        self.assertEqual(charm.weight_lb, 1.0)
        self.assertEqual(backpack.stored_in, STORED_WORN)

    async def test_equips_first_weapon_when_attacks_are_not_gear(self) -> None:
        sheet = CharacterSheet(name="Sasmen", abilities={"dex": 12, "str": 15})
        catalog = {
            "chain mail": {
                "slug": "chain-mail",
                "name": "Chain Mail",
                "kind": ITEM_KIND_ARMOR,
                "weight_lb": 55,
            },
            "shield": {
                "slug": "shield",
                "name": "Shield",
                "kind": ITEM_KIND_ARMOR,
                "weight_lb": 6,
            },
            "longsword": {
                "slug": "longsword",
                "name": "Longsword",
                "kind": ITEM_KIND_WEAPON,
                "weight_lb": 3,
            },
            "javelin": {
                "slug": "javelin",
                "name": "Javelin",
                "kind": ITEM_KIND_WEAPON,
                "weight_lb": 2,
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
                await fill_sheet_equipment(
                    sheet,
                    entries=[
                        ("Chain Mail", 1),
                        ("Shield", 1),
                        ("Longsword", 1),
                        ("Javelin", 6),
                    ],
                    equipped_names=[],
                )

        sword = sheet.equipment.find_item("Longsword")
        javelin = sheet.equipment.find_item("Javelin")
        armor = sheet.equipment.find_item("Chain Mail")
        shield = sheet.equipment.find_item("Shield")
        assert sword and javelin and armor and shield
        self.assertTrue(sword.equipped)
        self.assertEqual(sword.stored_in, STORED_HANDS)
        self.assertFalse(javelin.equipped)
        self.assertTrue(armor.equipped)
        self.assertTrue(shield.equipped)

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


class TestPreserveLiveSheetFields(unittest.TestCase):
    def test_keeps_existing_wallet_and_hunger(self) -> None:
        from sheets.commands.import_cmd import preserve_live_sheet_fields
        from sheets.currency import Currency

        existing = CharacterSheet(
            name="Old",
            hunger_days=1.5,
            fed_today="full",
            image_url="https://example.com/a.png",
            currency=Currency(gp=42, sp=3),
        )
        imported = CharacterSheet(name="New", currency=Currency(gp=10))
        preserve_live_sheet_fields(imported, existing)
        self.assertEqual(imported.currency.gp, 42)
        self.assertEqual(imported.currency.sp, 3)
        self.assertEqual(imported.hunger_days, 1.5)
        self.assertEqual(imported.fed_today, "full")
        self.assertEqual(imported.image_url, "https://example.com/a.png")
        self.assertEqual(imported.name, "New")


if __name__ == "__main__":
    unittest.main()
