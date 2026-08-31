import unittest

from srd import fivetools
from srd.fivetools.loader import get_index, reload_index
from srd.spell_slugs import migrate_spell_slugs, normalize_stored_spell_slug


def setUpModule() -> None:
    reload_index()


class TestSpellSlugs(unittest.TestCase):
    def test_short_slug_unchanged(self) -> None:
        self.assertEqual(normalize_stored_spell_slug("fireball"), "fireball")

    def test_strips_document_prefix(self) -> None:
        self.assertEqual(normalize_stored_spell_slug("srd-2024_fireball"), "fireball")
        self.assertEqual(normalize_stored_spell_slug("wotc-srd_fireball"), "fireball")

    def test_preserves_homebrew(self) -> None:
        slug = "homebrew:My%20Spell"
        self.assertEqual(normalize_stored_spell_slug(slug), slug)

    def test_migrate_deduplicates(self) -> None:
        migrated, changed = migrate_spell_slugs(
            ["fireball", "srd-2024_fireball", "fireball"]
        )
        self.assertTrue(changed)
        self.assertEqual(migrated, ["fireball"])


class TestFiveToolsNormalize(unittest.TestCase):
    def test_normalize_spell_from_raw(self) -> None:
        index = get_index()
        raw = index.spells_by_name["blood bolt"]
        self.assertEqual(raw["source"], "CrookedMoon24")
        spell = fivetools.normalize_spell(raw)
        self.assertEqual(spell["name"], "Blood Bolt")
        self.assertEqual(spell["level"], "Cantrip")
        self.assertEqual(spell["document__slug"], "CrookedMoon24")

    def test_normalize_condition(self) -> None:
        raw = get_index().conditions_by_name["bleeding"]
        condition = fivetools.normalize_condition(raw)
        assert condition is not None
        self.assertIn("Bleeding", condition["name"])

    def test_normalize_weapon(self) -> None:
        raw = get_index().weapons_by_name["long sword"]
        weapon = fivetools.normalize_weapon(raw)
        self.assertEqual(weapon["name"], "Long Sword")
        self.assertEqual(weapon["damage"], "1d8")

    def test_short_slug_helpers(self) -> None:
        self.assertEqual(fivetools.short_slug("srd-2024_fireball"), "fireball")
        self.assertEqual(fivetools.api_key("fireball"), "fireball_xphb")

    def test_entry_url(self) -> None:
        url = fivetools.entry_url("class", "Kindred", source="BoundByBlood")
        self.assertTrue(url.startswith("https://5e.tools/classes.html#"))
        self.assertIn("kindred", url.lower())

    def test_entry_url_maps_phb_to_xphb(self) -> None:
        url = fivetools.entry_url("spell", "Fireball", source="PHB")
        self.assertIn("_xphb", url.lower())
        self.assertNotIn("_phb", url.lower().split("_xphb")[0])

    def test_normalize_spell_url_uses_xphb(self) -> None:
        raw = get_index().spells_by_name["fireball"]
        spell = fivetools.normalize_spell(raw)
        self.assertIn("xphb", spell["url"].lower())
        self.assertNotIn("_phb", spell["url"].lower().replace("_xphb", ""))


class TestFiveToolsSearch(unittest.IsolatedAsyncioTestCase):
    async def test_search_official_spell(self) -> None:
        spell = await fivetools.search_spell("Fireball")
        self.assertEqual(spell["name"], "Fireball")
        self.assertEqual(spell["document__slug"], "XPHB")

        from srd.embeds import spell_embed, spell_embed_color

        embed = spell_embed(spell)
        self.assertEqual(spell_embed_color(spell), 0xE74C3C)
        self.assertEqual(embed.color.value, 0xE74C3C)
        self.assertIn("✨", embed.title)
        self.assertIn("📊 Level", [field.name for field in embed.fields])

    async def test_get_spell(self) -> None:
        spell = await fivetools.get_spell("blood-bolt")
        self.assertEqual(spell["name"], "Blood Bolt")
        self.assertEqual(spell["document__slug"], "CrookedMoon24")

    async def test_get_spell_with_source_suffix(self) -> None:
        spell = await fivetools.get_spell("blood-bolt__crookedmoon24")
        self.assertEqual(spell["name"], "Blood Bolt")

    async def test_search_spell(self) -> None:
        spell = await fivetools.search_spell("Blood Bolt")
        self.assertEqual(spell["slug"], "blood-bolt__crookedmoon24")

    async def test_search_equipment(self) -> None:
        entry = await fivetools.search_equipment("Long Sword")
        self.assertEqual(entry["name"], "Long Sword")

    async def test_search_equipment_shield_is_the_basic_shield(self) -> None:
        entry = await fivetools.search_equipment("shield")
        self.assertEqual(entry["name"], "Shield")
        self.assertEqual(entry["kind"], "armor")
        self.assertEqual(entry["ac"], "2")

    async def test_search_class_has_subclasses(self) -> None:
        char_class = await fivetools.search_class("Kindred")
        self.assertGreaterEqual(len(char_class["archetypes"]), 1)
        match = fivetools.find_subclass(char_class=char_class, query="Brujah")
        self.assertIsNotNone(match)

    async def test_search_kindred_from_brew(self) -> None:
        char_class = await fivetools.search_class("Kindred")
        self.assertEqual(char_class["name"], "Kindred")
        self.assertEqual(char_class["document__slug"], "BoundByBlood")
        self.assertGreaterEqual(len(char_class["archetypes"]), 1)
        url = fivetools.entry_url("class", "Kindred", source="BoundByBlood")
        self.assertIn("boundbyblood", url.lower())


class TestMonstersAndCache(unittest.IsolatedAsyncioTestCase):
    async def test_search_xmm_monster(self) -> None:
        monster = await fivetools.search_monster("Goblin Warrior")
        self.assertEqual(monster["name"], "Goblin Warrior")
        self.assertEqual(monster["document__slug"], "XMM")
        self.assertIn("_xmm", monster["url"].lower())
        self.assertNotEqual(monster["hp"], "—")
        self.assertTrue(monster["actions"])
        self.assertIn("Chaotic Neutral", monster["stat_line"])
        self.assertIn("Passive Perception", monster["senses"])
        self.assertIn("Melee Attack Roll:", monster["actions"])
        self.assertIn("🗡️ Slashing", monster["actions"])
        self.assertNotIn("XPHB", monster["actions"])
        self.assertIn("```", monster["abilities"])

    async def test_nested_condition_immunities(self) -> None:
        archmage = await fivetools.search_monster("Archmage")
        self.assertIn("Charmed", archmage["condition_immune"])
        self.assertIn("Mind Blank", archmage["condition_immune"])
        self.assertNotIn("{", archmage["condition_immune"])

    def test_format_damage_list_prenote(self) -> None:
        from srd.fivetools.lookup import _format_damage_list

        rendered = _format_damage_list(
            [
                {
                    "resist": ["bludgeoning"],
                    "preNote": "While wearing the ring:",
                    "note": "nonmagical",
                }
            ]
        )
        self.assertIn("While wearing the ring", rendered)
        self.assertIn("🔨 Bludgeoning", rendered)
        self.assertIn("nonmagical", rendered)

    async def test_spellcasting_daily_labels(self) -> None:
        aeromancer = await fivetools.search_monster("Aarakocra Aeromancer")
        self.assertIn("1/day:", aeromancer["spellcasting"])
        self.assertNotRegex(aeromancer["spellcasting"], r"\*1:\*")

        dragon = await fivetools.search_monster("Adult Black Dragon")
        self.assertTrue(
            "1/day each:" in dragon["spellcasting"]
            or "1/day:" in dragon["spellcasting"],
            dragon["spellcasting"],
        )

    async def test_monster_embed_uses_type_color(self) -> None:
        from srd.embeds import monster_embed, monster_embed_color

        goblin = await fivetools.search_monster("Goblin Warrior")
        aboleth = await fivetools.search_monster("Aboleth")

        goblin_embed = monster_embed(goblin)
        aboleth_embed = monster_embed(aboleth)

        self.assertEqual(monster_embed_color(goblin), 0x43A047)
        self.assertEqual(monster_embed_color(aboleth), 0x7B2CBF)
        self.assertEqual(goblin_embed.color.value, 0x43A047)
        self.assertEqual(aboleth_embed.color.value, 0x7B2CBF)
        self.assertIn("🍃", goblin_embed.title)
        self.assertIn("🟢 CR", goblin_embed.description or "")
        self.assertIn("⚔️ Actions", [field.name for field in goblin_embed.fields])
        self.assertTrue(goblin["image_url"].endswith("Goblins.webp"))
        self.assertIn("Goblin%20Warrior.webp", goblin["token_url"])
        self.assertEqual(goblin_embed.image.url, goblin["image_url"])
        self.assertEqual(goblin_embed.thumbnail.url, goblin["token_url"])
        self.assertTrue(aboleth["image_url"].endswith("Aboleth.webp"))
        self.assertEqual(aboleth_embed.image.url, aboleth["image_url"])

    async def test_monster_embed_fields_fit_discord_after_linkify(self) -> None:
        from bot.messaging import prepare_outgoing
        from srd import glossary
        from srd.embeds import DISCORD_FIELD_LIMIT, MAX_EMBED_FIELDS, monster_embed

        await glossary.load()
        tarrasque = await fivetools.search_monster("Tarrasque")
        embed = monster_embed(tarrasque)
        _, prepared, _, _ = prepare_outgoing(embed=embed)
        assert prepared is not None
        self.assertLessEqual(len(prepared.fields), MAX_EMBED_FIELDS)
        for field in prepared.fields:
            self.assertLessEqual(len(field.name), 256, field.name)
            self.assertLessEqual(len(field.value), DISCORD_FIELD_LIMIT, field.name)
        self.assertTrue(
            any(field.name.startswith("⚔️ Actions") for field in prepared.fields)
        )

    async def test_search_monster_partial(self) -> None:
        monster = await fivetools.search_monster("Goblin")
        self.assertTrue(monster["name"].lower().startswith("goblin"))
        self.assertEqual(monster["document__slug"], "XMM")

    async def test_search_weapon_fuzzy_missing_space(self) -> None:
        weapon = await fivetools.search_weapon("longsword")
        self.assertEqual(_compact(weapon["name"]), "longsword")

    async def test_search_monster_fuzzy_typo(self) -> None:
        monster = await fivetools.search_monster("goblin warroir")
        self.assertIn("goblin", monster["name"].lower())
        self.assertIn("warrior", monster["name"].lower())

    async def test_collect_search_matches_lists_similar_monsters(self) -> None:
        matches = fivetools.collect_search_matches("monster", "goblin")
        names = [item["name"].lower() for item in matches]
        self.assertGreater(len(matches), 1)
        self.assertTrue(any("goblin" in name for name in names))

    async def test_partial_item_query_is_ambiguous(self) -> None:
        self.assertTrue(fivetools.has_exact_name_match("item", "bag of holding"))
        self.assertIsNone(fivetools.lookup_candidates("item", "bag of holding"))
        self.assertIsNone(fivetools.lookup_candidates("spell", "fire"))

        candidates = fivetools.lookup_candidates("item", "bag")
        self.assertIsNotNone(candidates)
        assert candidates is not None
        self.assertGreater(len(candidates), 1)
        names = [item["name"].lower() for item in candidates]
        self.assertTrue(any("bag" in name for name in names))

        forced = fivetools.lookup_candidates("monster", "goblin", force_list=True)
        self.assertIsNotNone(forced)
        assert forced is not None
        self.assertGreater(len(forced), 1)

    async def test_render_cache_reuses_spell(self) -> None:
        first = await fivetools.search_spell("Fireball")
        second = await fivetools.search_spell("Fireball")
        self.assertIs(first, second)

    async def test_suggest_names_from_index(self) -> None:
        suggestions = fivetools.suggest_names("spell", "fireb")
        self.assertTrue(any(name.lower() == "fireball" for name in suggestions))
        monster_names = fivetools.suggest_names("monster", "goblin")
        self.assertTrue(any("goblin" in name.lower() for name in monster_names))

    async def test_wizard_class_is_paginated(self) -> None:
        from srd.class_view import build_class_pages

        wizard = await fivetools.search_class("Wizard")
        self.assertEqual(wizard["source"], "XPHB")
        self.assertGreater(len(wizard.get("features") or []), 3)
        pages = build_class_pages(wizard)
        self.assertGreater(len(pages), 1)
        self.assertIn("1/", pages[0].footer.text or "")


def _compact(value: str) -> str:
    return "".join(value.lower().split())


class TestSearchQuery(unittest.TestCase):
    def test_parse_search_query_detects_tilde(self) -> None:
        self.assertEqual(
            fivetools.parse_search_query("  longsword "), ("longsword", False)
        )
        self.assertEqual(fivetools.parse_search_query("~goblin"), ("goblin", True))
        self.assertEqual(
            fivetools.parse_search_query("~ Goblin Warrior"), ("Goblin Warrior", True)
        )


if __name__ == "__main__":
    unittest.main()
