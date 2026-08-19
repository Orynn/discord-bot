import unittest

from sheets.data import CharacterSheet
from sheets.embeds import build_sheet_embed
from sheets.skills import format_skill_line, skill_rule_slug, skill_url


class TestSkills(unittest.TestCase):
    def test_skill_rule_slug(self) -> None:
        self.assertEqual(skill_rule_slug("animal_handling"), "animal-handling")

    def test_skill_url(self) -> None:
        self.assertTrue(skill_url("acrobatics").startswith("https://5e.tools/skills.html#"))

    def test_format_skill_line(self) -> None:
        line = format_skill_line(skill="stealth", ability="dex", modifier="+5")
        self.assertIn("[Stealth]", line)
        self.assertIn("5e.tools/skills.html", line)

    def test_sheet_embed_includes_skill_links(self) -> None:
        sheet = CharacterSheet(name="Rogue")
        sheet.abilities["dex"] = 16
        sheet.skill_proficiencies.append("stealth")
        embed = build_sheet_embed(sheet=sheet)
        description = embed.description or ""
        self.assertIn("[Stealth]", description)
        self.assertIn("5e.tools/skills.html", description)
        self.assertIn("📋", embed.title)
        self.assertIn("🛡️ AC", [field.name for field in embed.fields])


if __name__ == "__main__":
    unittest.main()
