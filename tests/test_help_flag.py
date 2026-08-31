import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.events import register_events
from bot.help_commands import (
    CommandHelpShown,
    is_command_help_shown,
    leftover_argument_tokens,
    maybe_send_command_help,
    tokens_request_help,
    wants_command_help,
)
from sheets.commands import setup_sheet
from srd.commands import setup_srd


def _ctx(*, rest: str = "", command=True, interaction=None) -> MagicMock:
    ctx = MagicMock()
    ctx.command = object() if command else None
    ctx.interaction = interaction
    ctx.view = MagicMock()
    ctx.view.rest = rest
    ctx.send_help = AsyncMock()
    return ctx


class TestCommandHelpFlag(unittest.IsolatedAsyncioTestCase):
    def test_detects_dash_h(self) -> None:
        self.assertTrue(wants_command_help(_ctx(rest=" -h")))
        self.assertTrue(wants_command_help(_ctx(rest="--help")))
        self.assertTrue(wants_command_help(_ctx(rest="Wolf -h")))
        self.assertTrue(wants_command_help(_ctx(rest="-H")))
        self.assertTrue(wants_command_help(_ctx(rest="help")))
        self.assertTrue(wants_command_help(_ctx(rest="aide")))
        self.assertTrue(wants_command_help(_ctx(rest="-h", interaction=object())))

    def test_word_help_only_when_leftover_is_help(self) -> None:
        self.assertTrue(tokens_request_help(["help"]))
        self.assertTrue(tokens_request_help(["--help"]))
        self.assertFalse(tokens_request_help(["investigation", "help"]))
        self.assertFalse(tokens_request_help(["athletics"]))

    def test_slash_kwargs_are_leftover_tokens(self) -> None:
        ctx = _ctx(rest="")
        ctx.kwargs = {"member": None, "args": "--help"}
        self.assertEqual(leftover_argument_tokens(ctx), ["--help"])
        self.assertTrue(wants_command_help(ctx))

    def test_slash_help_ignores_roll_option_kwargs(self) -> None:
        ctx = _ctx(rest="")
        ctx.interaction = object()
        ctx.kwargs = {
            "member": None,
            "args": "help",
            "avantage": "advantage",
            "bonus": 2,
        }
        self.assertEqual(leftover_argument_tokens(ctx), ["help"])
        self.assertTrue(wants_command_help(ctx))

    def test_ignores_normal_args(self) -> None:
        self.assertFalse(wants_command_help(_ctx(rest="")))
        self.assertFalse(wants_command_help(_ctx(rest="Wolf 2h")))
        self.assertFalse(wants_command_help(_ctx(rest="-h", command=False)))
        self.assertFalse(wants_command_help(_ctx(rest="investigation help")))

    async def test_sends_help_instead_of_running(self) -> None:
        ctx = _ctx(rest="-h")
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(ctx.command)

    async def test_leaves_normal_invoke_alone(self) -> None:
        ctx = _ctx(rest="Wolf")
        handled = await maybe_send_command_help(ctx)
        self.assertFalse(handled)
        ctx.send_help.assert_not_awaited()

    async def test_help_word_targets_subcommand(self) -> None:
        show = SimpleNamespace(name="show")
        start = SimpleNamespace(name="start")
        sheet = SimpleNamespace(all_commands={"show": show, "hp": show})
        combat = SimpleNamespace(all_commands={"start": start, "board": start})

        ctx = _ctx(rest="show help")
        ctx.command = sheet
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(show)

        ctx = _ctx(rest="start -h")
        ctx.command = combat
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(start)

    async def test_nested_subcommand_help(self) -> None:
        short = SimpleNamespace(name="short")
        rest = SimpleNamespace(all_commands={"short": short, "long": short})
        sheet = SimpleNamespace(all_commands={"rest": rest, "show": rest})
        ctx = _ctx(rest="rest short help")
        ctx.command = sheet
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(short)

    def test_group_help_without_subcommand(self) -> None:
        sheet = SimpleNamespace(all_commands={"show": SimpleNamespace()})
        ctx = _ctx(rest="help")
        ctx.command = sheet
        self.assertTrue(wants_command_help(ctx))

    def test_word_help_does_not_steal_required_query(self) -> None:
        query = SimpleNamespace(
            default=inspect.Parameter.empty, annotation=str
        )
        spell = SimpleNamespace(
            name="spell",
            all_commands={},
            clean_params={"query": query},
        )
        srd = SimpleNamespace(all_commands={"spell": spell})
        ctx = _ctx(rest="spell help")
        ctx.command = srd
        self.assertFalse(wants_command_help(ctx))

    def test_word_help_still_works_for_required_value(self) -> None:
        value = SimpleNamespace(
            default=inspect.Parameter.empty, annotation=str
        )
        setter = SimpleNamespace(
            name="set",
            all_commands={},
            clean_params={"value": value},
        )
        sheet = SimpleNamespace(all_commands={"set": setter})
        ctx = _ctx(rest="set help")
        ctx.command = sheet
        self.assertTrue(wants_command_help(ctx))

    def test_dash_h_still_helps_required_query(self) -> None:
        query = SimpleNamespace(
            default=inspect.Parameter.empty, annotation=str
        )
        spell = SimpleNamespace(
            name="spell",
            all_commands={},
            clean_params={"query": query},
        )
        srd = SimpleNamespace(all_commands={"spell": spell})
        ctx = _ctx(rest="spell -h")
        ctx.command = srd
        self.assertTrue(wants_command_help(ctx))

    async def test_slash_kwargs_help_is_detected(self) -> None:
        ctx = _ctx(rest="")
        ctx.interaction = object()
        ctx.kwargs = {"member": None, "args": "help"}
        ctx.command = SimpleNamespace(clean_params={"args": SimpleNamespace(default="")})
        self.assertTrue(wants_command_help(ctx))
        handled = await maybe_send_command_help(ctx)
        self.assertTrue(handled)
        ctx.send_help.assert_awaited_once_with(ctx.command)


class TestRealCommandHelpParams(unittest.TestCase):
    def setUp(self) -> None:
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix=";", intents=intents)
        setup_sheet(self.bot)
        setup_srd(self.bot)

    def test_sheet_set_word_help_shows_help(self) -> None:
        ctx = _ctx(rest="set help")
        ctx.command = self.bot.get_command("sheet")
        self.assertTrue(wants_command_help(ctx))

    def test_srd_spell_word_help_is_lookup(self) -> None:
        ctx = _ctx(rest="spell help")
        ctx.command = self.bot.get_command("srd")
        self.assertFalse(wants_command_help(ctx))

    def test_srd_spell_dash_h_shows_help(self) -> None:
        ctx = _ctx(rest="spell -h")
        ctx.command = self.bot.get_command("srd")
        self.assertTrue(wants_command_help(ctx))


class TestCommandHelpShown(unittest.IsolatedAsyncioTestCase):
    def test_detects_bare_and_wrapped(self) -> None:
        self.assertTrue(is_command_help_shown(CommandHelpShown()))
        self.assertFalse(is_command_help_shown(commands.CheckFailure("nope")))
        wrapped = commands.CommandInvokeError(CommandHelpShown())
        self.assertTrue(is_command_help_shown(wrapped))
        caused = commands.CheckFailure("outer")
        caused.__cause__ = CommandHelpShown()
        self.assertTrue(is_command_help_shown(caused))

    async def test_on_command_error_does_not_treat_help_as_permission(
        self,
    ) -> None:
        intents = discord.Intents.none()
        bot = commands.Bot(command_prefix=";", intents=intents)
        register_events(bot)
        ctx = MagicMock()
        ctx.guild = object()
        with patch("bot.events._error_reply", new_callable=AsyncMock) as reply:
            await bot.on_command_error(ctx, CommandHelpShown())
        reply.assert_not_awaited()

