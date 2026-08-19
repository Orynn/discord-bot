import unittest

from sheets.embeds import sheet_info_embeds


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


if __name__ == "__main__":
    unittest.main()
