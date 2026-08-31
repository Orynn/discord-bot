import unittest

from players.format import format_player_category_name


class TestPlayerCategoryFormat(unittest.TestCase):
    def test_leo_style(self) -> None:
        self.assertEqual(
            format_player_category_name("leo", width=25, emoji="🐉"),
            "🐉-----------LEO-----------🐉",
        )

    def test_uppercases_name(self) -> None:
        self.assertIn(
            "ARAGORN", format_player_category_name("Aragorn", width=25, emoji="🐉")
        )

    def test_rejects_empty_name(self) -> None:
        with self.assertRaises(ValueError):
            format_player_category_name("   ")


if __name__ == "__main__":
    unittest.main()
