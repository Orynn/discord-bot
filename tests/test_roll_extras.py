import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from roll.commands import RerollView, prepare_roll_request, roll_embed
from sheets.data import CharacterSheet
from sheets.dice import (
    MAX_REPEAT,
    execute_roll,
    format_roll_embed,
    format_roll_series_embed,
    parse_bonus,
    parse_dice,
    parse_roll_args,
    suggest_modifier,
)


def _roll(args: str, *, sheet: CharacterSheet | None = None, faces=None):
    request = parse_roll_args(args)
    kwargs = {"side_effect": faces} if faces is not None else {"return_value": 10}
    with patch("sheets.dice.random.randint", **kwargs):
        return execute_roll(
            dice=request.dice,
            sheet=sheet,
            modifier_tokens=request.modifier_tokens,
            advantage=request.advantage,
            dc=request.dc,
        )


class TestDifficultyClass(unittest.TestCase):
    def test_dc_spellings(self) -> None:
        for args in ("d20+5 vs 15", "d20+5 dd 15", "DC15 d20+5", "d20+5 contre 15"):
            with self.subTest(args=args):
                self.assertEqual(parse_roll_args(args).dc, 15)

    def test_dc_missing_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "Il manque le DD"):
            parse_roll_args("d20 vs")

    def test_verdict_in_embed(self) -> None:
        success = _roll("d20+5 vs 15", faces=[10])
        self.assertTrue(success.success)
        self.assertIn(
            "✅ Réussite (DD 15)",
            format_roll_embed(success, roller_label="A").description,
        )
        failure = _roll("d20+5 vs 16", faces=[10])
        self.assertFalse(failure.success)
        self.assertIn(
            "❌ Échec (DD 16)", format_roll_embed(failure, roller_label="A").description
        )


class TestRepeatCritLabelSecret(unittest.TestCase):
    def test_repeat(self) -> None:
        self.assertEqual(parse_roll_args("3x d20+5").repeat, 3)
        self.assertEqual(parse_roll_args("6x 4d6kh3").repeat, 6)
        with self.assertRaises(ValueError):
            parse_roll_args(f"{MAX_REPEAT + 1}x d20")

    def test_series_embed(self) -> None:
        results = [
            _roll("4d6kh3", faces=[6, 5, 3, 2]),
            _roll("4d6kh3", faces=[1, 1, 1, 1]),
        ]
        embed = format_roll_series_embed(results, roller_label="Hero", label="stats")
        self.assertIn("2 jets", embed.title)
        self.assertIn("stats", embed.title)
        lines = embed.description.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("**14**", lines[0])
        self.assertIn("~~2~~", lines[0])
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Σ Somme"], "17")

    def test_crit_doubles_dice_not_modifier(self) -> None:
        request = parse_roll_args("crit 2d6+1d8+3")
        self.assertEqual(request.dice.count, 4)
        self.assertEqual(request.dice.extra_dice[0].count, 2)
        self.assertEqual(request.dice.flat_modifier, 3)
        with self.assertRaisesRegex(ValueError, "dés de dégâts"):
            parse_roll_args("crit athletics")

    def test_label_and_secret(self) -> None:
        request = parse_roll_args("secret d20+5 # épée  longue")
        self.assertEqual(request.label, "épée longue")
        self.assertTrue(request.secret)
        self.assertEqual(request.modifier_tokens, [])
        embed = format_roll_embed(_roll("d20+5"), roller_label="A", label=request.label)
        self.assertTrue(embed.title.endswith("· épée longue"))


class TestRerollDice(unittest.TestCase):
    def test_reroll_notation(self) -> None:
        dice = parse_dice("2d6r2+3")
        self.assertEqual((dice.count, dice.reroll_below, dice.flat_modifier), (2, 2, 3))
        result = _roll("2d6r2", faces=[1, 5, 4])
        self.assertEqual(result.dice_rolls, (5, 4))
        self.assertEqual(result.rerolls, ((1, 5),))
        self.assertEqual(result.dice_notation, "2d6r2")
        embed = format_roll_embed(result, roller_label="A")
        self.assertIn("🔁 Relancé : ~~1~~ → 5", embed.fields[1].value)

    def test_reroll_everything_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_dice("2d6r6")


class TestFrenchErrors(unittest.TestCase):
    def test_invalid_notation_is_french(self) -> None:
        with self.assertRaisesRegex(ValueError, "Notation de dés invalide"):
            parse_dice("d")

    def test_suggestions(self) -> None:
        self.assertEqual(suggest_modifier("athltisme"), "athlétisme")
        self.assertEqual(suggest_modifier("perceptoin"), "perception")
        self.assertIsNone(suggest_modifier("zzzz"))

    def test_unknown_modifier_suggests(self) -> None:
        with self.assertRaisesRegex(ValueError, "Tu voulais dire `athlétisme`"):
            _roll("athltisme", sheet=CharacterSheet(name="A"))


class TestSheetEffects(unittest.TestCase):
    def test_bless_on_attack_and_save(self) -> None:
        sheet = CharacterSheet(name="A", conditions=["béni"])
        result = _roll("d20+5", sheet=sheet, faces=[10, 3])
        self.assertEqual(result.total, 18)
        self.assertIn("🙏 Bénédiction +1d4", result.effect_notes)
        self.assertEqual(result.dice_notation, "1d20+1d4+5")
        save = _roll("sauvegarde dex", sheet=sheet, faces=[10, 3])
        self.assertEqual(save.total, 13)

    def test_bless_not_on_ability_check(self) -> None:
        sheet = CharacterSheet(name="A", conditions=["blessed"])
        result = _roll("athletics", sheet=sheet, faces=[10])
        self.assertEqual(result.extra_rolls, ())

    def test_bane(self) -> None:
        sheet = CharacterSheet(name="A", conditions=["fléau"])
        result = _roll("d20", sheet=sheet, faces=[10, 3])
        self.assertEqual(result.total, 7)

    def test_halfling_lucky(self) -> None:
        sheet = CharacterSheet(name="A", species="Halfelin pied-léger")
        result = _roll("d20", sheet=sheet, faces=[1, 15])
        self.assertEqual(result.total, 15)
        self.assertTrue(result.lucky_used)
        embed = format_roll_embed(result, roller_label="A")
        self.assertIn("🍀 Chanceux", embed.fields[1].value)
        damage = _roll("1d6", sheet=sheet, faces=[1])
        self.assertEqual(damage.total, 1)
        self.assertFalse(damage.lucky_used)


class TestBonusOption(unittest.TestCase):
    def test_parse_bonus(self) -> None:
        self.assertEqual(parse_bonus(2), (2, ()))
        self.assertEqual(parse_bonus("-1"), (-1, ()))
        flat, extras = parse_bonus("1d4 + 2")
        self.assertEqual(flat, 2)
        self.assertEqual([(e.sign, e.count, e.sides) for e in extras], [(1, 1, 4)])
        with self.assertRaisesRegex(ValueError, "Bonus invalide"):
            parse_bonus("beaucoup")

    def test_prepare_with_dice_bonus(self) -> None:
        request = prepare_roll_request("athletics", bonus="1d4")
        self.assertEqual([e.sides for e in request.dice.extra_dice], [4])
        self.assertIsNotNone(prepare_roll_request("", bonus="1d4"))


class TestRerollView(unittest.IsolatedAsyncioTestCase):
    def _view(self) -> RerollView:
        return RerollView(
            author_id=1,
            request=parse_roll_args("2x d20+5 vs 12 # attaque"),
            owner_id=1,
            guild_id=9,
            roller_label="**Hero**",
            secret=False,
        )

    async def test_only_author_can_reroll(self) -> None:
        view = self._view()
        interaction = MagicMock()
        interaction.user.id = 2
        interaction.response.send_message = AsyncMock()
        self.assertFalse(await view.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()
        interaction.user.id = 1
        self.assertTrue(await view.interaction_check(interaction))

    async def test_reroll_posts_new_roll(self) -> None:
        view = self._view()
        interaction = MagicMock()
        with (
            patch("roll.commands.get_sheet", return_value=None),
            patch(
                "roll.commands.send_interaction_message", new_callable=AsyncMock
            ) as send,
        ):
            await view.reroll.callback(interaction)
        embed = send.await_args.kwargs["embed"]
        self.assertIn("2 jets", embed.title)
        self.assertIn("attaque", embed.title)
        self.assertIsInstance(send.await_args.kwargs["view"], RerollView)

    def test_roll_embed_saves_spent_inspiration(self) -> None:
        sheet = CharacterSheet(name="Hero", inspired=True)
        with (
            patch("roll.commands.save_sheet") as save,
            patch("sheets.dice.random.randint", return_value=12),
        ):
            roll_embed(
                request=parse_roll_args("d20"),
                owner_id=1,
                guild_id=9,
                sheet=sheet,
                roller_label="Hero",
            )
        save.assert_called_once()
        self.assertFalse(sheet.inspired)


if __name__ == "__main__":
    unittest.main()
