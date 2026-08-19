import unittest

from srd.fivetools_parser import clean_tags, damage_type, format_damage_type_label, render_entries


class TestFiveToolsParser(unittest.TestCase):
    def test_variantrule_tag_uses_name_not_source(self) -> None:
        text = clean_tags("{@variantrule Advantage|XPHB}")
        self.assertEqual(text, "Advantage")

    def test_variantrule_tag_uses_display_alias(self) -> None:
        text = clean_tags("{@variantrule Emanation [Area of Effect]|XPHB|Emanation}")
        self.assertEqual(text, "Emanation")

    def test_condition_and_spell_tags(self) -> None:
        text = clean_tags(
            "has the {@condition Grappled|XPHB} condition and casts {@spell Fireball|XPHB}"
        )
        self.assertIn("Grappled", text)
        self.assertIn("Fireball", text)
        self.assertNotIn("XPHB", text)

    def test_attack_and_save_tags(self) -> None:
        text = clean_tags(
            "{@atkr m} {@hit 4}, reach 5 ft. {@h}5 ({@damage 1d6 + 2}) Slashing damage. "
            "{@actSave con} {@dc 14}. {@actSaveFail} 10 ({@damage 2d6}) Cold damage. {@actSaveSuccess} Half damage."
        )
        self.assertIn("Melee Attack Roll:", text)
        self.assertIn("Hit: 5", text)
        self.assertIn("🗡️ Slashing", text)
        self.assertIn("❄️ Cold", text)
        self.assertIn("Constitution Saving Throw:", text)
        self.assertIn("Failure:", text)
        self.assertIn("Success:", text)

    def test_damage_type_label(self) -> None:
        self.assertEqual(format_damage_type_label("fire"), "🔥 Fire")
        self.assertEqual(format_damage_type_label("🔥 Fire"), "🔥 Fire")
        self.assertEqual(damage_type("S"), "🗡️ Slashing")

    def test_spell_damage_type_label(self) -> None:
        from srd.fivetools_parser import spell_damage_type_label

        self.assertEqual(spell_damage_type_label({"damageInflict": ["fire"]}), "🔥 Fire")
        self.assertEqual(spell_damage_type_label({"damage_types": ["force"]}), "💫 Force")

    def test_hom_tag(self) -> None:
        text = clean_tags("{@hom}The javelin returns.")
        self.assertEqual(text, "Hit or Miss: The javelin returns.")

    def test_does_not_emojify_force_in_normal_sentences(self) -> None:
        text = clean_tags("The spell can force the target to move.")
        self.assertEqual(text, "The spell can force the target to move.")
        self.assertNotIn("💫", text)

    def test_emojify_only_damage_phrases(self) -> None:
        text = clean_tags("taking {@damage 8d6} Fire damage on a failed save")
        self.assertIn("🔥 Fire damage", text)
        self.assertNotIn("🔥 🔥", text)

    def test_spell_level_int(self) -> None:
        from srd.fivetools_parser import spell_level_int

        self.assertEqual(spell_level_int("Cantrip"), 0)
        self.assertEqual(spell_level_int("3rd"), 3)
        self.assertEqual(spell_level_int(1), 1)

    def test_render_named_block(self) -> None:
        rendered = render_entries(
            {
                "name": "Scimitar",
                "entries": [
                    "{@atkr m} {@hit 4}, reach 5 ft. {@h}5 ({@damage 1d6 + 2}) Slashing damage."
                ],
            }
        )
        self.assertIn("**Scimitar.**", rendered)
        self.assertIn("Melee Attack Roll:", rendered)


if __name__ == "__main__":
    unittest.main()
