import unittest

from combat.setup import parse_start_args


class TestParseStartArgs(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(parse_start_args(""), (None, None, "arena"))

    def test_monster_only(self) -> None:
        self.assertEqual(parse_start_args("Wolf"), ("Wolf", None, "arena"))
        self.assertEqual(parse_start_args("Dire Wolf"), ("Dire Wolf", None, "arena"))

    def test_monster_and_duration(self) -> None:
        self.assertEqual(parse_start_args("Wolf 2h"), ("Wolf", 120, "arena"))
        self.assertEqual(parse_start_args("Dire Wolf +2h"), ("Dire Wolf", 120, "arena"))

    def test_duration_only(self) -> None:
        self.assertEqual(parse_start_args("2h"), (None, 120, "arena"))

    def test_map_name(self) -> None:
        self.assertEqual(parse_start_args("tavern"), (None, None, "tavern"))
        self.assertEqual(parse_start_args("Wolf tavern"), ("Wolf", None, "tavern"))
        self.assertEqual(
            parse_start_args("Dire Wolf dungeon 2h"), ("Dire Wolf", 120, "dungeon")
        )
