import unittest

from sheets.data import CharacterSheet
from sheets.embeds import build_sheet_embed, sheet_info_embeds
from sheets.equipment import ITEM_KIND_CUSTOM, custom_slug


class TestSheetInfoEmbeds(unittest.TestCase):
    def test_partial_sheet_info_includes_missing_note(self) -> None:
        embeds = sheet_info_embeds(
            sheet_name="Alice",
            species={"name": "Human", "slug": "human", "document__title": "Test"},
            char_class=None,
            background=None,
            missing=["Class **Fighter**"],
        )
        self.assertEqual(len(embeds), 2)
        self.assertIn("Alice — Not in 5etools export", embeds[-1].title)
        self.assertIn("Fighter", embeds[-1].description)

    def test_all_missing_returns_empty_without_note(self) -> None:
        embeds = sheet_info_embeds(
            sheet_name="Bob",
            species=None,
            char_class=None,
            background=None,
            missing=["Class **Wizard**"],
        )
        self.assertEqual(len(embeds), 1)
        self.assertIn("Not in 5etools export", embeds[0].title)


class TestSheetShowHands(unittest.TestCase):
    def test_shows_empty_hands(self) -> None:
        embed = build_sheet_embed(sheet=CharacterSheet(name="Hero"))
        hands = next(
            field for field in embed.fields if field.name.startswith("🖐️ Hands")
        )
        self.assertEqual(hands.name, "🖐️ Hands (0/2)")
        self.assertEqual(hands.value, "—")

    def test_shows_held_items(self) -> None:
        from sheets.containers import STORED_HANDS

        sheet = CharacterSheet(name="Hero")
        sheet.equipment.add_item(
            slug=custom_slug("Torch"),
            name="Torch",
            kind=ITEM_KIND_CUSTOM,
            stored_in=STORED_HANDS,
        )
        sheet.equipment.add_item(
            slug=custom_slug("Dagger"),
            name="Dagger",
            kind=ITEM_KIND_CUSTOM,
            stored_in=STORED_HANDS,
        )
        embed = build_sheet_embed(sheet=sheet)
        hands = next(
            field for field in embed.fields if field.name.startswith("🖐️ Hands")
        )
        self.assertEqual(hands.name, "🖐️ Hands (2/2)")
        self.assertIn("Torch", hands.value)
        self.assertIn("Dagger", hands.value)
        self.assertNotIn("**Torch**", hands.value)
        self.assertNotIn("**Dagger**", hands.value)

    def test_shows_belt_items(self) -> None:
        from sheets.containers import STORED_BELT

        embed = build_sheet_embed(sheet=CharacterSheet(name="Hero"))
        belt = next(field for field in embed.fields if field.name.startswith("🪢 Belt"))
        self.assertEqual(belt.name, "🪢 Belt (0/4)")
        self.assertEqual(belt.value, "—")

        sheet = CharacterSheet(name="Hero")
        sheet.equipment.add_item(
            slug=custom_slug("Potion"),
            name="Potion",
            kind=ITEM_KIND_CUSTOM,
            stored_in=STORED_BELT,
        )
        embed = build_sheet_embed(sheet=sheet)
        belt = next(field for field in embed.fields if field.name.startswith("🪢 Belt"))
        self.assertEqual(belt.name, "🪢 Belt (1/4)")
        self.assertIn("Potion", belt.value)
        self.assertNotIn("**Potion**", belt.value)


if __name__ == "__main__":
    unittest.main()
