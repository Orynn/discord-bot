import unittest

from sheets.currency import Currency, parse_currency
from sheets.dice import (
    RollResult,
    execute_roll,
    format_roll_embed,
    parse_dice,
    parse_roll_args,
)
from sheets.data import CharacterSheet


class TestCurrency(unittest.TestCase):
    def test_parse_single_coin(self) -> None:
        currency = parse_currency("50 gp")
        self.assertEqual(currency.total_cp(), 5000)

    def test_parse_mixed_coins(self) -> None:
        currency = parse_currency("5 gp 3 sp 7 cp")
        self.assertEqual(currency.total_cp(), 5 * 100 + 3 * 10 + 7)

    def test_subtract_insufficient_funds(self) -> None:
        wallet = parse_currency("10 gp")
        cost = parse_currency("15 gp")
        self.assertFalse(wallet.subtract(cost))

    def test_add_normalizes(self) -> None:
        wallet = parse_currency("9 sp")
        wallet.add(parse_currency("1 sp"))
        self.assertEqual(wallet.gp, 1)

    def test_coin_weight(self) -> None:
        self.assertEqual(Currency(gp=50).weight_lb(), 1)
        self.assertEqual(Currency().weight_lb(), 0)


class TestDice(unittest.TestCase):
    def test_parse_dice_with_modifier(self) -> None:
        dice = parse_dice("2d6+3")
        self.assertEqual(dice.count, 2)
        self.assertEqual(dice.sides, 6)
        self.assertEqual(dice.flat_modifier, 3)

    def test_parse_keep_highest(self) -> None:
        dice = parse_dice("2d20kh1")
        self.assertEqual(dice.keep_mode, "kh")
        self.assertEqual(dice.keep_count, 1)

    def test_parse_roll_args_defaults_to_d20(self) -> None:
        request = parse_roll_args("athletics")
        self.assertEqual(request.dice.count, 1)
        self.assertEqual(request.dice.sides, 20)
        self.assertEqual(request.modifier_tokens, ["athletics"])

    def test_execute_roll_with_sheet_skill(self) -> None:
        sheet = CharacterSheet(
            name="Test",
            level=5,
            abilities={
                "str": 16,
                "dex": 10,
                "con": 10,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
            skill_proficiencies=["athletics"],
        )
        request = parse_roll_args("1d20 athletics")
        result = execute_roll(
            dice=request.dice,
            sheet=sheet,
            modifier_tokens=request.modifier_tokens,
            advantage=None,
        )
        self.assertIn("Athletics", result.modifier_label)
        self.assertEqual(result.sheet_modifier, 6)

    def test_french_skill_and_advantage_aliases(self) -> None:
        sheet = CharacterSheet(
            name="Test",
            level=5,
            abilities={
                "str": 10,
                "dex": 16,
                "con": 10,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
            skill_proficiencies=["stealth"],
        )
        request = parse_roll_args("discrétion")
        self.assertEqual(request.dice.sides, 20)
        self.assertIsNone(request.advantage)
        result = execute_roll(
            dice=request.dice,
            sheet=sheet,
            modifier_tokens=request.modifier_tokens,
            advantage=request.advantage,
        )
        self.assertIn("Stealth", result.modifier_label)
        self.assertEqual(result.sheet_modifier, 6)

        adv = parse_roll_args("avantage discrétion")
        self.assertTrue(adv.advantage)
        self.assertEqual(adv.modifier_tokens, ["discrétion"])

        dis = parse_roll_args("désavantage tromperie")
        self.assertFalse(dis.advantage)
        from sheets.dice import resolve_sheet_modifier

        modifier, label = resolve_sheet_modifier(sheet, ["acrobaties"])
        self.assertIn("Acrobatics", label)
        modifier, label = resolve_sheet_modifier(sheet, ["escamotage"])
        self.assertIn("Sleight Of Hand", label)

    def test_format_roll_embed_nat20(self) -> None:
        result = RollResult(
            dice_notation="1d20+5",
            dice_rolls=(20,),
            kept_rolls=(20,),
            flat_modifier=5,
            sheet_modifier=0,
            modifier_label="",
            total=25,
            advantage=None,
        )
        embed = format_roll_embed(result, roller_label="Hero")
        self.assertIn("🎲 Hero", embed.title)
        self.assertEqual(embed.description, "**25**")
        self.assertEqual(embed.color.value, 0x27AE60)
        self.assertEqual(embed.footer.text, "🌟 Natural 20!")
        self.assertIn("🧮 Breakdown", [field.name for field in embed.fields])

    def test_format_roll_embed_advantage(self) -> None:
        result = RollResult(
            dice_notation="1d20",
            dice_rolls=(14,),
            kept_rolls=(14,),
            flat_modifier=0,
            sheet_modifier=3,
            modifier_label="STR (+3)",
            total=17,
            advantage=True,
            d20_pair=(14, 8),
        )
        embed = format_roll_embed(result, roller_label="Fighter")
        self.assertEqual(embed.color.value, 0x2980B9)
        rolls_field = next(field for field in embed.fields if field.name == "🎲 Rolls")
        self.assertIn("⬆️ Advantage", rolls_field.value)
        self.assertIn("~~8~~", rolls_field.value)

    def test_inspiration_grants_advantage_on_d20(self) -> None:
        from unittest.mock import patch

        sheet = CharacterSheet(name="Test", inspired=True)
        request = parse_roll_args("1d20")
        with patch("sheets.dice.random.randint", side_effect=[4, 18]):
            result = execute_roll(
                dice=request.dice,
                sheet=sheet,
                modifier_tokens=request.modifier_tokens,
                advantage=None,
            )
        self.assertTrue(result.spent_inspiration)
        self.assertTrue(result.advantage)
        self.assertFalse(sheet.inspired)
        self.assertEqual(result.dice_rolls, (18,))

    def test_inspiration_cancels_condition_disadvantage(self) -> None:
        from unittest.mock import patch

        sheet = CharacterSheet(
            name="Test",
            inspired=True,
            conditions=["poisoned"],
            abilities={
                "str": 16,
                "dex": 10,
                "con": 10,
                "int": 10,
                "wis": 10,
                "cha": 10,
            },
            skill_proficiencies=["athletics"],
        )
        request = parse_roll_args("athletics")
        with patch("sheets.dice.random.randint", return_value=11):
            result = execute_roll(
                dice=request.dice,
                sheet=sheet,
                modifier_tokens=request.modifier_tokens,
                advantage=None,
            )
        self.assertTrue(result.spent_inspiration)
        self.assertIsNone(result.advantage)
        self.assertEqual(result.condition_note, "poisoned")
        self.assertFalse(sheet.inspired)

    def test_requested_advantage_keeps_inspiration(self) -> None:
        from unittest.mock import patch

        sheet = CharacterSheet(name="Test", inspired=True)
        request = parse_roll_args("adv 1d20")
        with patch("sheets.dice.random.randint", side_effect=[4, 18]):
            result = execute_roll(
                dice=request.dice,
                sheet=sheet,
                modifier_tokens=request.modifier_tokens,
                advantage=request.advantage,
            )
        self.assertFalse(result.spent_inspiration)
        self.assertTrue(sheet.inspired)
        self.assertTrue(result.advantage)


if __name__ == "__main__":
    unittest.main()
