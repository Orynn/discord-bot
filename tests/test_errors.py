import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.errors import (
    collect_command_names,
    format_command_suggestions,
    invoked_command_name,
    suggest_commands,
)
from bot.events import register_events
from roll.commands import setup_roll
from scene.commands import setup_desc
from sheets.commands import setup_sheet


class TestCommandSuggestions(unittest.TestCase):
    def test_suggests_close_command_names(self) -> None:
        names = ["roll", "sheet create", "desc"]
        self.assertEqual(suggest_commands("rol", names), ["roll"])
        self.assertEqual(suggest_commands("shee create", names), ["sheet create"])
        self.assertEqual(suggest_commands("c'est", names), [])
        self.assertEqual(suggest_commands("r", names), [])

    def test_formats_french_hint(self) -> None:
        self.assertEqual(
            format_command_suggestions(["roll"]),
            "Commande inconnue. Tu voulais dire `;roll` ?",
        )
        self.assertIn("`;desc`", format_command_suggestions(["roll", "desc"]))

    def test_reads_invoked_name_from_error(self) -> None:
        error = commands.CommandNotFound('Command "rol" is not found')
        self.assertEqual(invoked_command_name(error, "rol"), "rol")
        self.assertEqual(invoked_command_name(error, None), "rol")


class TestCollectCommandNames(unittest.TestCase):
    def test_includes_qualified_names_and_aliases(self) -> None:
        bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
        setup_roll(bot)
        setup_desc(bot)
        setup_sheet(bot)
        names = collect_command_names(bot)
        self.assertIn("roll", names)
        self.assertIn("r", names)
        self.assertIn("desc", names)
        self.assertIn("sheet create", names)
        self.assertNotIn("help", names)


class TestCommandErrorHandler(unittest.IsolatedAsyncioTestCase):
    def _bot(self) -> commands.Bot:
        bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
        setup_roll(bot)
        register_events(bot)
        return bot

    async def test_unknown_command_suggests_roll(self) -> None:
        bot = self._bot()
        ctx = MagicMock()
        ctx.invoked_with = "rol"
        ctx.command = None
        ctx.guild = object()
        with patch("bot.events._error_reply", new_callable=AsyncMock) as reply:
            await bot.on_command_error(ctx, commands.CommandNotFound('Command "rol" is not found'))
        reply.assert_awaited_once()
        self.assertIn(";roll", reply.await_args.args[1])

    async def test_unknown_unrelated_text_stays_quiet(self) -> None:
        bot = self._bot()
        ctx = MagicMock()
        ctx.invoked_with = "c'est"
        ctx.command = None
        with patch("bot.events._error_reply", new_callable=AsyncMock) as reply:
            await bot.on_command_error(
                ctx, commands.CommandNotFound('Command "c\'est" is not found')
            )
        reply.assert_not_awaited()

    async def test_missing_argument_sends_pretty_help(self) -> None:
        bot = self._bot()
        setup_sheet(bot)
        ctx = MagicMock()
        ctx.command = bot.get_command("sheet create")
        ctx.send_help = AsyncMock()
        ctx._from_catchup = False
        param = ctx.command.clean_params["name"]
        with patch("bot.events._error_reply", new_callable=AsyncMock) as reply:
            await bot.on_command_error(ctx, commands.MissingRequiredArgument(param))
        ctx.send_help.assert_awaited_once_with(ctx.command)
        reply.assert_not_awaited()
