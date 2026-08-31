import unittest

from campaign.clock import CampaignTime
from sheets.data import CharacterSheet
from sheets.embeds import build_sheet_embed, build_status_embed, sheet_info_embeds
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

    def test_url_portrait_is_thumbnail(self) -> None:
        sheet = CharacterSheet(
            name="Hero", image_url="https://example.com/hero.png"
        )
        embed = build_sheet_embed(sheet=sheet)
        self.assertEqual(embed.thumbnail.url, "https://example.com/hero.png")

    def test_attached_portrait_uses_attachment_url(self) -> None:
        embed = build_sheet_embed(
            sheet=CharacterSheet(name="Hero"),
            portrait_filename="portrait.png",
        )
        self.assertEqual(embed.thumbnail.url, "attachment://portrait.png")


class TestStatusEmbed(unittest.TestCase):
    def test_recap_shows_vitals_hunger_and_rest(self) -> None:
        sheet = CharacterSheet(
            name="Anorak",
            hp_current=8,
            hp_max=14,
            inspired=True,
            conditions=["poisoned"],
            hunger_days=1,
            fed_today="half",
            hit_dice_remaining=2,
            level=5,
            hunger_meal_year=1492,
            hunger_meal_day=0,
            hunger_meal_kind="half",
        )
        clock = CampaignTime(year=1492, day_index=1, minute=22 * 60)
        embed = build_status_embed(sheet, who="Anorak", clock=clock)
        names = [field.name for field in embed.fields]
        self.assertEqual(embed.title, "📌 Status — Anorak")
        self.assertNotIn("**", embed.title)
        self.assertIn("❤️ HP", names)
        self.assertIn("🍖 Hunger", names)
        self.assertIn("🏕️ Sleep & rest", names)
        self.assertIn("📅 Time", names)
        self.assertIn("Last meal", names)
        hp = next(field for field in embed.fields if field.name == "❤️ HP")
        self.assertIn("8/14", hp.value)
        conditions = next(
            field for field in embed.fields if field.name == "🩹 Conditions"
        )
        self.assertIn("Poisoned", conditions.value)
        inspiration = next(
            field for field in embed.fields if field.name == "✨ Inspiration"
        )
        self.assertIn("Heroic Inspiration", inspiration.value)
        hunger = next(field for field in embed.fields if field.name == "🍖 Hunger")
        self.assertIn("1 day", hunger.value)
        rest = next(field for field in embed.fields if field.name == "🏕️ Sleep & rest")
        self.assertIn("2/5", rest.value)
        time_field = next(field for field in embed.fields if field.name == "📅 Time")
        self.assertIn("night", time_field.value)

    def test_recap_hides_death_saves_when_healthy(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=10, hp_max=10)
        embed = build_status_embed(sheet)
        names = [field.name for field in embed.fields]
        self.assertNotIn("💀 Death saves", names)
        conditions = next(
            field for field in embed.fields if field.name == "🩹 Conditions"
        )
        self.assertEqual(conditions.value, "none")

    def test_recap_shows_death_saves_when_dying(self) -> None:
        sheet = CharacterSheet(
            name="Hero",
            hp_current=0,
            hp_max=10,
            death_save_successes=1,
            death_save_failures=2,
        )
        embed = build_status_embed(sheet)
        death = next(field for field in embed.fields if field.name == "💀 Death saves")
        self.assertIn("1", death.value)
        self.assertIn("2", death.value)

    def test_recap_shows_starvation_notices(self) -> None:
        sheet = CharacterSheet(name="Hero", hp_current=10, hp_max=10)
        embed = build_status_embed(
            sheet, notices=["starvation → exhaustion 1"]
        )
        starvation = next(
            field for field in embed.fields if field.name == "⚠️ Starvation"
        )
        self.assertIn("exhaustion 1", starvation.value)


if __name__ == "__main__":
    unittest.main()
