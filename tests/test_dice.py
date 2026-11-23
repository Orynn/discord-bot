import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord.ext import commands

from roll.commands import _leading_member, prepare_roll_request
from sheets.currency import Currency, parse_currency
from sheets.dice import (
    RollResult,
    apply_roll_options,
    execute_roll,
    format_roll_embed,
    parse_advantage_flag,
    parse_dice,
    parse_roll_args,
    resolve_sheet_modifier,
    validate_roll_request,
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

    def test_parse_dice_without_count(self) -> None:
        dice = parse_dice("d20+5")
        self.assertEqual((dice.count, dice.sides, dice.flat_modifier), (1, 20, 5))

    def test_parse_dice_chained_modifiers(self) -> None:
        self.assertEqual(parse_dice("2d6+3-1").flat_modifier, 2)

    def test_parse_roll_args_manual_rolls(self) -> None:
        cases = {
            "d20+5": (20, 5, []),
            "d20 + 5": (20, 5, []),
            "1d20 -2": (20, -2, []),
            "+3": (20, 3, []),
            "athletics + 2": (20, 2, ["athletics"]),
            "dex save -1": (20, -1, ["dex", "save"]),
        }
        for args, (sides, flat, tokens) in cases.items():
            with self.subTest(args=args):
                request = parse_roll_args(args)
                self.assertEqual(request.dice.sides, sides)
                self.assertEqual(request.dice.flat_modifier, flat)
                self.assertEqual(request.modifier_tokens, tokens)

    def test_parse_dice_extra_dice_groups(self) -> None:
        dice = parse_dice("1d20+1d4-d6+5")
        self.assertEqual((dice.count, dice.sides, dice.flat_modifier), (1, 20, 5))
        self.assertEqual(
            [(e.sign, e.count, e.sides) for e in dice.extra_dice],
            [(1, 1, 4), (-1, 1, 6)],
        )

    def test_parse_roll_args_spaced_and_bare_extra_dice(self) -> None:
        spaced = parse_roll_args("adv d20 + 1d4 + 3")
        self.assertEqual(spaced.advantage, True)
        self.assertEqual(spaced.dice.flat_modifier, 3)
        self.assertEqual([e.sides for e in spaced.dice.extra_dice], [4])
        guidance = parse_roll_args("athletics +d4")
        self.assertEqual(guidance.modifier_tokens, ["athletics"])
        self.assertEqual([e.sides for e in guidance.dice.extra_dice], [4])
        validate_roll_request(spaced)

    def test_parse_dice_total_count_limit(self) -> None:
        with self.assertRaises(ValueError):
            parse_dice("60d6+60d6")

    def test_execute_roll_with_extra_dice(self) -> None:
        request = parse_roll_args("1d20+1d4-1d6+2")
        with patch("sheets.dice.random.randint", side_effect=[20, 3, 5]):
            result = execute_roll(
                dice=request.dice,
                sheet=None,
                modifier_tokens=request.modifier_tokens,
                advantage=request.advantage,
            )
        self.assertEqual(result.dice_notation, "1d20+1d4-1d6+2")
        self.assertEqual(result.total, 20 + 3 - 5 + 2)
        embed = format_roll_embed(result, roller_label="Test")
        self.assertIn("Critique", embed.title)
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("+ 1d4 : **3**", fields["🎲 Dés"])
        self.assertIn("- 1d6 : **5**", fields["🎲 Dés"])
        self.assertEqual(fields["🧮 Calcul"], "20 + 3 - 5 + 2 = **20**")

    def test_extra_d20_is_not_a_crit(self) -> None:
        request = parse_roll_args("1d4+1d20")
        with patch("sheets.dice.random.randint", side_effect=[1, 20]):
            result = execute_roll(
                dice=request.dice,
                sheet=None,
                modifier_tokens=request.modifier_tokens,
                advantage=None,
            )
        self.assertNotIn("Critique", format_roll_embed(result, roller_label="T").title)

    def test_manual_roll_needs_no_sheet(self) -> None:
        request = parse_roll_args("d20+5")
        result = execute_roll(
            dice=request.dice,
            sheet=None,
            modifier_tokens=request.modifier_tokens,
            advantage=request.advantage,
        )
        self.assertEqual(result.dice_notation, "1d20+5")
        self.assertEqual(result.total, result.dice_rolls[0] + 5)

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
        self.assertIn("Athlétisme", result.modifier_label)
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
        self.assertIn("Discrétion", result.modifier_label)
        self.assertEqual(result.sheet_modifier, 6)

        adv = parse_roll_args("avantage discrétion")
        self.assertTrue(adv.advantage)
        self.assertEqual(adv.modifier_tokens, ["discrétion"])

        trailing = parse_roll_args("investigation advantage")
        self.assertTrue(trailing.advantage)
        self.assertEqual(trailing.modifier_tokens, ["investigation"])

        dis = parse_roll_args("désavantage tromperie")
        self.assertFalse(dis.advantage)

        modifier, label = resolve_sheet_modifier(sheet, ["acrobaties"])
        self.assertIn("Acrobaties", label)
        modifier, label = resolve_sheet_modifier(sheet, ["escamotage"])
        self.assertIn("Escamotage", label)

    def test_slash_options_add_bonus_and_advantage(self) -> None:
        request = parse_roll_args("athletics")
        merged = apply_roll_options(request, bonus=2, advantage=True)
        self.assertEqual(merged.dice.flat_modifier, 2)
        self.assertTrue(merged.advantage)
        self.assertEqual(merged.modifier_tokens, ["athletics"])
        validate_roll_request(merged)

        stacked = apply_roll_options(parse_roll_args("2d6+3"), bonus=-1)
        self.assertEqual(stacked.dice.flat_modifier, 2)

    def test_slash_advantage_conflicts_with_args(self) -> None:
        request = parse_roll_args("adv athletics")
        with self.assertRaises(ValueError):
            apply_roll_options(request, advantage=False)

    def test_parse_advantage_flag(self) -> None:
        self.assertTrue(parse_advantage_flag("avantage"))
        self.assertFalse(parse_advantage_flag("désavantage"))
        self.assertIsNone(parse_advantage_flag(None))
        self.assertIsNone(parse_advantage_flag(""))
        with self.assertRaises(ValueError):
            parse_advantage_flag("athletics")

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
        self.assertIn("Critique", embed.title)
        self.assertIn("Hero", embed.title)
        self.assertIn("**20**", embed.description)
        self.assertIn("**25**", embed.description)
        self.assertEqual(embed.color.value, 0x27AE60)
        self.assertIn("🧮 Calcul", [field.name for field in embed.fields])
        rolls_field = next(field for field in embed.fields if field.name == "🎲 Dés")
        self.assertIn("Critique", rolls_field.value)

    def test_format_roll_embed_nat1(self) -> None:
        result = RollResult(
            dice_notation="1d20",
            dice_rolls=(1,),
            kept_rolls=(1,),
            flat_modifier=0,
            sheet_modifier=0,
            modifier_label="",
            total=1,
            advantage=None,
        )
        embed = format_roll_embed(result, roller_label="Hero")
        self.assertIn("Échec critique", embed.title)
        self.assertIn("**1**", embed.description)
        self.assertEqual(embed.color.value, 0xC0392B)

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
        rolls_field = next(field for field in embed.fields if field.name == "🎲 Dés")
        self.assertIn("⬆️ Avantage", rolls_field.value)
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

    def test_unknown_modifier_raises(self) -> None:
        sheet = CharacterSheet(name="Test")
        with self.assertRaisesRegex(ValueError, "Je ne connais pas"):
            resolve_sheet_modifier(sheet, ["help"])


class TestPrepareRollRequest(unittest.TestCase):
    def test_empty_args_without_options_is_help(self) -> None:
        self.assertIsNone(prepare_roll_request(""))

    def test_bonus_only_defaults_to_d20(self) -> None:
        request = prepare_roll_request("", bonus=3)
        assert request is not None
        self.assertEqual(request.dice.count, 1)
        self.assertEqual(request.dice.sides, 20)
        self.assertEqual(request.dice.flat_modifier, 3)

    def test_avantage_option_on_skill(self) -> None:
        request = prepare_roll_request("perception", avantage="disadvantage")
        assert request is not None
        self.assertFalse(request.advantage)
        self.assertEqual(request.modifier_tokens, ["perception"])


class TestLeadingMember(unittest.IsolatedAsyncioTestCase):
    async def test_first_word_names_a_member(self) -> None:
        alice = MagicMock()
        with patch.object(
            commands.MemberConverter, "convert", AsyncMock(return_value=alice)
        ):
            member, rest = await _leading_member(MagicMock(), "Alice athletics")
        self.assertIs(member, alice)
        self.assertEqual(rest, "athletics")

    async def test_unknown_word_keeps_args(self) -> None:
        with patch.object(
            commands.MemberConverter,
            "convert",
            AsyncMock(side_effect=commands.MemberNotFound("perception")),
        ):
            member, rest = await _leading_member(MagicMock(), "perception adv")
        self.assertIsNone(member)
        self.assertEqual(rest, "perception adv")

    async def test_single_word_is_never_a_member(self) -> None:
        member, rest = await _leading_member(MagicMock(), "perception")
        self.assertIsNone(member)
        self.assertEqual(rest, "perception")


if __name__ == "__main__":
    unittest.main()
