import unittest

from campaign.clock import (
    CampaignTime,
    format_duration,
    parse_clock_set,
    parse_duration,
    parse_skip_period,
    year_length,
)


class TestHarptosClock(unittest.TestCase):
    def test_default_is_first_of_hammer(self) -> None:
        clock = CampaignTime()
        self.assertEqual(clock.format_date(), "the 1st of Hammer, 1492 DR")
        self.assertEqual(clock.format_clock(), "08:00")
        self.assertEqual(clock.period(), "morning")

    def test_advance_hours_and_days(self) -> None:
        clock = CampaignTime().advance(parse_duration("2h"))
        self.assertEqual(clock.format_clock(), "10:00")
        clock = clock.advance(parse_duration("3d"))
        self.assertEqual(clock.calendar_day().day, 4)
        self.assertEqual(clock.format_clock(), "10:00")

    def test_rolls_into_festival(self) -> None:
        clock = parse_clock_set("30 Hammer 1492 8:00")
        nxt = clock.advance(parse_duration("1d"))
        self.assertTrue(nxt.calendar_day().festival)
        self.assertEqual(nxt.calendar_day().name, "Midwinter")

    def test_leap_year_has_shieldmeet(self) -> None:
        self.assertEqual(year_length(1492), 366)
        clock = parse_clock_set("Shieldmeet 1492 12:00")
        self.assertTrue(clock.calendar_day().festival)
        self.assertEqual(clock.calendar_day().name, "Shieldmeet")
        with self.assertRaises(ValueError):
            parse_clock_set("Shieldmeet 1491 12:00")

    def test_parse_set_variants(self) -> None:
        clock = parse_clock_set("the 12th of Hammer 1492 14:00")
        self.assertEqual(clock.calendar_day().day, 12)
        self.assertEqual(clock.format_clock(), "14:00")
        self.assertEqual(clock.period(), "afternoon")
        clock = parse_clock_set("Midwinter 1492 8h")
        self.assertEqual(clock.calendar_day().name, "Midwinter")

    def test_parse_duration_tokens(self) -> None:
        self.assertEqual(parse_duration("1h30"), 90)
        self.assertEqual(parse_duration("1h 30m"), 90)
        self.assertEqual(parse_duration("2 days"), 2 * 24 * 60)
        self.assertEqual(parse_duration("3j"), 3 * 24 * 60)
        self.assertEqual(parse_duration("long"), 8 * 60)
        self.assertEqual(parse_duration("short"), 60)

    def test_skip_to_next_dawn(self) -> None:
        clock = parse_clock_set("1 Hammer 1492 07:00")
        nxt = clock.skip_to_hour(6)
        self.assertEqual(nxt.calendar_day().day, 2)
        self.assertEqual(nxt.format_clock(), "06:00")
        self.assertEqual(parse_skip_period("aube"), 6)

    def test_round_trip_dict(self) -> None:
        clock = parse_clock_set("12 Hammer 1492 14:32")
        restored = CampaignTime.from_dict(clock.to_dict())
        self.assertEqual(restored.format_line(), clock.format_line())

    def test_format_duration(self) -> None:
        self.assertEqual(format_duration(90), "1 hour, 30 minutes")
        self.assertEqual(format_duration(24 * 60), "1 day")


class TestPerPlayerClockStorage(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        import data.db as db_module
        from data.db import init_db

        self._db_module = db_module
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        init_db()

    def tearDown(self) -> None:
        self._db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_players_on_same_guild_have_separate_clocks(self) -> None:
        from campaign.clock_storage import get_clock, save_clock

        alice = parse_clock_set("12 Hammer 1492 14:00")
        bob = parse_clock_set("1 Ches 1492 08:00")
        save_clock(1, 10, alice)
        save_clock(1, 11, bob)

        self.assertEqual(get_clock(1, 10).format_line(), alice.format_line())
        self.assertEqual(get_clock(1, 11).format_line(), bob.format_line())
        self.assertEqual(get_clock(2, 10).format_clock(), CampaignTime().format_clock())

    def test_legacy_guild_clock_seeds_new_players(self) -> None:
        from data.db import set_json
        from campaign.clock_storage import get_clock, save_clock

        shared = parse_clock_set("20 Hammer 1492 18:00")
        set_json("campaign_clock:1", shared.to_dict())

        seeded = get_clock(1, 10)
        self.assertEqual(seeded.format_line(), shared.format_line())

        advanced = seeded.advance(60)
        save_clock(1, 10, advanced)
        self.assertEqual(get_clock(1, 10).format_clock(), "19:00")
        self.assertEqual(get_clock(1, 11).format_clock(), "18:00")


if __name__ == "__main__":
    unittest.main()
