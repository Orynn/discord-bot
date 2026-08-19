import unittest

from bot.help_text import build_combat_help_sections, build_help_sections


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
