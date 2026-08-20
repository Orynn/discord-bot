import tempfile
import unittest
from pathlib import Path

import data.db as db_module
from campaign.clock import CampaignTime, calendar_days_between, parse_duration
from sheets.data import CharacterSheet
from sheets.embeds import build_sheet_embed
from sheets.equipment import ITEM_KIND_ITEM
from sheets.hunger import (
    advance_hunger,
    consume_ration,
    eat_full,
    eat_half,
    exhaustion_level,
    format_hunger_line,
    hunger_state,
    parse_hunger_days,
    set_hunger_days,
    skip_hunger_day,
    starvation_limit,
    tick_hunger_for_clock,
)
from sheets.storage import get_sheet, save_sheet


class TestHungerRules(unittest.TestCase):
    def test_starvation_limit_uses_constitution(self) -> None:
        self.assertEqual(starvation_limit(10), 3)
        self.assertEqual(starvation_limit(14), 5)
        self.assertEqual(starvation_limit(6), 1)

    def test_eat_full_resets_hunger(self) -> None:
        sheet = CharacterSheet(name="Graosh", hunger_days=2.5)
        eat_full(sheet)
        self.assertEqual(sheet.hunger_days, 0.0)
        self.assertEqual(sheet.fed_today, "full")
        self.assertEqual(hunger_state(sheet), "fed")

    def test_half_rations_then_new_day(self) -> None:
        sheet = CharacterSheet(name="Ilidor")
        eat_half(sheet)
        notices = advance_hunger(sheet, 1)
        self.assertEqual(notices, [])
        self.assertEqual(sheet.hunger_days, 0.5)
        self.assertEqual(sheet.fed_today, "")
        self.assertEqual(hunger_state(sheet), "hungry")

    def test_new_day_without_food_adds_a_day(self) -> None:
        sheet = CharacterSheet(name="Chagrin")
        advance_hunger(sheet, 2)
        self.assertEqual(sheet.hunger_days, 2.0)

    def test_eating_prevents_the_next_day_tick(self) -> None:
        sheet = CharacterSheet(name="Labreb")
        eat_full(sheet)
        advance_hunger(sheet, 1)
        self.assertEqual(sheet.hunger_days, 0.0)
        self.assertEqual(sheet.fed_today, "")

    def test_starvation_adds_exhaustion_past_the_limit(self) -> None:
        sheet = CharacterSheet(name="Ping")
        notices = skip_hunger_day(sheet)
        self.assertEqual(notices, [])
        notices = advance_hunger(sheet, 3)
        self.assertEqual(sheet.hunger_days, 4.0)
        self.assertEqual(exhaustion_level(sheet), 1)
        self.assertTrue(any("exhaustion 1" in notice for notice in notices))
        self.assertEqual(hunger_state(sheet), "starving")

    def test_multi_day_skip_stacks_exhaustion(self) -> None:
        sheet = CharacterSheet(name="Fox", hunger_days=3)
        notices = advance_hunger(sheet, 2)
        self.assertEqual(sheet.hunger_days, 5.0)
        self.assertEqual(exhaustion_level(sheet), 2)
        self.assertEqual(len(notices), 2)

    def test_set_zero_marks_fed(self) -> None:
        sheet = CharacterSheet(name="Max", hunger_days=4, fed_today="")
        set_hunger_days(sheet, 0)
        self.assertEqual(sheet.hunger_days, 0.0)
        self.assertEqual(sheet.fed_today, "full")

    def test_parse_hunger_days(self) -> None:
        self.assertEqual(parse_hunger_days("2.5"), 2.5)
        self.assertEqual(parse_hunger_days("half"), 0.5)
        self.assertEqual(parse_hunger_days("fed"), 0.0)
        with self.assertRaises(ValueError):
            parse_hunger_days("nope")

    def test_consume_ration_removes_one(self) -> None:
        sheet = CharacterSheet(name="Leo")
        sheet.equipment.add_item(
            slug="rations",
            name="Rations",
            kind=ITEM_KIND_ITEM,
            quantity=3,
            auto_stow=False,
        )
        removed = consume_ration(sheet)
        assert removed is not None
        self.assertEqual(removed.name, "Rations")
        leftover = sheet.equipment.find_item("Rations")
        assert leftover is not None
        self.assertEqual(leftover.quantity, 2)

    def test_sheet_embed_shows_hunger_when_hungry(self) -> None:
        sheet = CharacterSheet(name="Hero", hunger_days=2)
        embed = build_sheet_embed(sheet)
        status = next(field for field in embed.fields if field.name == "📌 Status")
        self.assertIn("🍖", status.value)
        self.assertIn("2 days", status.value)

    def test_persists_on_sheet(self) -> None:
        raw = CharacterSheet(
            name="Hero",
            hunger_days=1.5,
            fed_today="half",
            hunger_meal_year=1492,
            hunger_meal_day=3,
            hunger_meal_kind="half",
        ).to_dict()
        loaded = CharacterSheet.from_dict(raw)
        self.assertEqual(loaded.hunger_days, 1.5)
        self.assertEqual(loaded.fed_today, "half")
        self.assertEqual(loaded.hunger_meal_year, 1492)
        self.assertEqual(loaded.hunger_meal_kind, "half")
        self.assertIn("1.5 days", format_hunger_line(loaded))


class TestHungerClockTick(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_calendar_days_between(self) -> None:
        start = CampaignTime()
        later = start.advance(parse_duration("2d"))
        self.assertEqual(calendar_days_between(start, later), 2)
        self.assertEqual(calendar_days_between(later, start), 0)

    def test_time_skip_ticks_hunger(self) -> None:
        save_sheet(user_id=1, guild_id=1, sheet=CharacterSheet(name="Graosh"))
        previous = CampaignTime()
        current = previous.advance(parse_duration("1d"))
        notices = tick_hunger_for_clock(
            guild_id=1,
            user_id=1,
            previous=previous,
            current=current,
        )
        self.assertTrue(any("1 day without food" in line for line in notices))
        sheet = get_sheet(user_id=1, guild_id=1)
        assert sheet is not None
        self.assertEqual(sheet.hunger_days, 1.0)

    def test_fed_character_stays_fed_across_midnight(self) -> None:
        sheet = CharacterSheet(name="Graosh")
        eat_full(sheet)
        save_sheet(user_id=1, guild_id=1, sheet=sheet)
        previous = CampaignTime()
        current = previous.advance(parse_duration("1d"))
        tick_hunger_for_clock(guild_id=1, user_id=1, previous=previous, current=current)
        loaded = get_sheet(user_id=1, guild_id=1)
        assert loaded is not None
        self.assertEqual(loaded.hunger_days, 0.0)

    def test_hunger_follows_clock_after_a_meal(self) -> None:
        clock = CampaignTime()
        sheet = CharacterSheet(name="Graosh")
        eat_full(sheet, clock)
        save_sheet(user_id=1, guild_id=1, sheet=sheet)
        later = clock.advance(parse_duration("2d"))
        tick_hunger_for_clock(guild_id=1, user_id=1, previous=clock, current=later)
        loaded = get_sheet(user_id=1, guild_id=1)
        assert loaded is not None
        self.assertEqual(loaded.hunger_days, 1.0)
        self.assertEqual(loaded.hunger_meal_kind, "full")

    def test_half_rations_then_clock_day(self) -> None:
        clock = CampaignTime()
        sheet = CharacterSheet(name="Ilidor")
        eat_half(sheet, clock)
        save_sheet(user_id=1, guild_id=1, sheet=sheet)
        later = clock.advance(parse_duration("1d"))
        tick_hunger_for_clock(guild_id=1, user_id=1, previous=clock, current=later)
        loaded = get_sheet(user_id=1, guild_id=1)
        assert loaded is not None
        self.assertEqual(loaded.hunger_days, 0.5)
        self.assertEqual(loaded.fed_today, "")

    def test_long_rest_advances_that_players_clock(self) -> None:
        from campaign.clock_storage import get_clock, save_clock
        from sheets.commands.status import advance_clock_for_long_rest

        save_sheet(user_id=1, guild_id=1, sheet=CharacterSheet(name="Graosh"))
        start = CampaignTime()
        save_clock(1, 1, start)
        note, _notices = advance_clock_for_long_rest(guild_id=1, user_id=1)
        later = get_clock(1, 1)
        self.assertEqual(later, start.advance(parse_duration("long")))
        self.assertIn("8 hours", note)


if __name__ == "__main__":
    unittest.main()
