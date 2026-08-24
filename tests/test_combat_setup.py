import unittest

from combat.setup import parse_start_args


class TestParseStartArgs(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertEqual(parse_start_args(""), (None, None))

    def test_monster_only(self) -> None:
        self.assertEqual(parse_start_args("Wolf"), ("Wolf", None))
        self.assertEqual(parse_start_args("Dire Wolf"), ("Dire Wolf", None))

    def test_monster_and_duration(self) -> None:
        self.assertEqual(parse_start_args("Wolf 2h"), ("Wolf", 120))
        self.assertEqual(parse_start_args("Dire Wolf +2h"), ("Dire Wolf", 120))

    def test_duration_only(self) -> None:
        self.assertEqual(parse_start_args("2h"), (None, 120))
