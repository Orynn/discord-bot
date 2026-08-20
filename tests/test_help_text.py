import unittest

from bot.help_text import (
    build_combat_help_sections,
    build_help_sections,
    build_hunger_help_sections,
    build_sheet_help_sections,
    build_srd_help_sections,
)


class TestHelpSections(unittest.TestCase):
    def test_main_help_includes_overview_and_combat(self) -> None:
        sections = build_help_sections(prefix=";", is_admin=False)
        keys = [section.key for section in sections]
        self.assertEqual(keys[0], "overview")
        self.assertIn("combat", keys)
        self.assertIn("initiative", keys)

    def test_combat_help_has_play_section(self) -> None:
        sections = build_combat_help_sections(prefix=";", is_admin=False)
        keys = [section.key for section in sections]
        self.assertEqual(keys[:4], ["start", "play", "deck", "init"])

    def test_combat_help_admin_section_only_for_admins(self) -> None:
        player_sections = build_combat_help_sections(prefix=";", is_admin=False)
        admin_sections = build_combat_help_sections(prefix=";", is_admin=True)
        self.assertEqual(len(player_sections), 4)
        self.assertEqual(len(admin_sections), 5)
        self.assertEqual(admin_sections[-1].key, "admin")

    def test_help_mentions_detailed_guides(self) -> None:
        overview = build_help_sections(prefix=";", is_admin=False)[0]
        self.assertIn(";help combat", overview.body)
        self.assertIn(";help sheet", overview.body)
        self.assertIn(";help srd", overview.body)
        self.assertIn(";help hunger", overview.body)

    def test_srd_help_has_examples_not_pipe_list(self) -> None:
        lookup = next(section for section in build_help_sections(prefix=";", is_admin=False) if section.key == "lookup")
        self.assertNotIn("spell|species", lookup.body)
        self.assertIn(";srd <type> <name>", lookup.body)
        self.assertIn(";help srd", lookup.body)

        sections = build_srd_help_sections(prefix=";")
        self.assertEqual([section.key for section in sections], ["lookup", "search"])
        self.assertIn(";srd <type> <name>", sections[0].body)
        self.assertIn("`monster`", sections[0].body)
        self.assertIn(";srd spell fireball", sections[0].footer or "")
        self.assertNotIn("spell|species", sections[0].body)

    def test_help_ties_hunger_to_the_clock(self) -> None:
        roleplay = next(
            section for section in build_help_sections(prefix=";", is_admin=False) if section.key == "roleplay"
        )
        self.assertIn("hunger follows that clock", roleplay.body)
        self.assertIn(";get naked", roleplay.body)
        self.assertIn(";image", roleplay.body)
        self.assertIn(";dessine", roleplay.body)

        sheet = next(
            section
            for section in build_sheet_help_sections(prefix=";", is_admin=False)
            if section.key == "status"
        )
        self.assertIn(";time", sheet.body)
        self.assertIn("calendar day", sheet.body)

        admin = next(
            section for section in build_help_sections(prefix=";", is_admin=True) if section.key == "admin"
        )
        self.assertIn("ticks that player's hunger", admin.body)
        self.assertIn(";hunger skip @player", admin.body)

        player = build_hunger_help_sections(prefix=";", is_admin=False)[0]
        self.assertIn("campaign clock", player.body)
        self.assertNotIn(";hunger skip", player.body)

        dm = build_hunger_help_sections(prefix=";", is_admin=True)[0]
        self.assertIn(";time advance 1d", dm.body)
        self.assertIn(";hunger skip @player", dm.body)

    def test_sheet_help_mentions_leaving_gear(self) -> None:
        resources = next(
            section
            for section in build_sheet_help_sections(prefix=";", is_admin=False)
            if section.key == "resources"
        )
        self.assertIn(";sheet gear let", resources.body)
        self.assertIn(";sheet gear take", resources.body)
        self.assertIn("updates AC", resources.body)

    def test_combat_help_requires_player_section(self) -> None:
        start = next(
            section
            for section in build_combat_help_sections(prefix=";", is_admin=False)
            if section.key == "start"
        )
        self.assertIn("player's OOC or roleplay channel", start.body)
        admin = next(
            section
            for section in build_combat_help_sections(prefix=";", is_admin=True)
            if section.key == "admin"
        )
        self.assertIn("player OOC/roleplay channel", admin.body)

    def test_help_embed_uses_section_color_and_fields(self) -> None:
        from bot.help_text import HELP_SHEET_COLOR, build_help_embed

        sections = build_help_sections(prefix=";", is_admin=False)
        overview = build_help_embed(title="Arkann — commands", sections=sections, index=0)
        sheet = build_help_embed(title="Arkann — commands", sections=sections, index=2)

        self.assertIn("📖", overview.title)
        self.assertIn("Quick start", overview.description or "")
        self.assertTrue(overview.fields)
        self.assertEqual(sheet.color.value, HELP_SHEET_COLOR)
        self.assertIn("📋", sheet.title)
