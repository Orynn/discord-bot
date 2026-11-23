import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

from bot.command_helpers import delete_command
from bot.help_commands import setup_help
from bot.slash import setup_slash
from bot.tree_utils import clamp_app_command_descriptions
from campaign.commands import setup_campaign
from campaign.time_commands import setup_time
from fun.commands import setup_fun
from npc.commands import setup_npc
from party.commands import setup_party
from pc.commands import setup_pc
from players.commands import setup_player
from combat.commands import setup_combat
from roll.commands import setup_roll
from scene.commands import setup_desc
from scene.rp_commands import setup_rp
from sheets.commands import setup_sheet
from srd.commands import setup_srd


def _register_commands(bot: commands.Bot) -> None:
    for setup in (
        setup_npc,
        setup_desc,
        setup_rp,
        setup_fun,
        setup_pc,
        setup_roll,
        setup_combat,
        setup_sheet,
        setup_party,
        setup_player,
        setup_srd,
        setup_campaign,
        setup_time,
        setup_help,
        setup_slash,
    ):
        setup(bot)


def _walk_descriptions(commands) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for command in commands:
        description = getattr(command, "description", "") or ""
        found.append((getattr(command, "qualified_name", command.name), description))
        children = getattr(command, "commands", None)
        if children:
            found.extend(_walk_descriptions(children))
    return found


class TestSlashRegistration(unittest.TestCase):
    def setUp(self) -> None:
        intents = discord.Intents.none()
        self.bot = commands.Bot(command_prefix=";", intents=intents)
        _register_commands(self.bot)
        clamp_app_command_descriptions(self.bot.tree)

    def test_registers_player_facing_slash_commands(self) -> None:
        names = {command.name for command in self.bot.tree.get_commands()}
        self.assertTrue(
            {
                "help",
                "aide",
                "roll",
                "sheet",
                "srd",
                "pc",
                "hp",
                "slots",
                "rest",
                "desc",
                "think",
                "whisper",
                "scene",
                "look",
                "campaign",
                "time",
                "get",
                "status",
                "tuto",
            }.issubset(names)
        )
        campaign = next(
            command
            for command in self.bot.tree.get_commands()
            if command.name == "campaign"
        )
        child_names = {child.name for child in campaign.commands}
        self.assertTrue(
            {
                "search",
                "post",
                "forum",
                "document",
                "wiki",
                "import",
                "channels",
                "audit",
                "move",
                "repair",
            }.issubset(child_names)
        )
        import_cmd = next(
            child for child in campaign.commands if child.name == "import"
        )
        option_names = {option.name for option in import_cmd.parameters}
        self.assertIn("query", option_names)
        self.assertIn("liens", option_names)

        roll = next(
            command
            for command in self.bot.tree.get_commands()
            if command.name == "roll"
        )
        roll_options = [option.name for option in roll.parameters]
        self.assertEqual(roll_options[0], "args")
        self.assertTrue({"args", "bonus", "avantage"}.issubset(roll_options))
        avantage = next(
            option for option in roll.parameters if option.name == "avantage"
        )
        choice_values = {choice.value for choice in (avantage.choices or [])}
        self.assertEqual(choice_values, {"advantage", "disadvantage"})

        desc = next(
            command
            for command in self.bot.tree.get_commands()
            if command.name == "desc"
        )
        child_names = {child.name for child in desc.commands}
        self.assertIn("text", child_names)
        narrate = next(child for child in desc.commands if child.name == "text")
        narrate_options = {option.name for option in narrate.parameters}
        self.assertTrue({"text", "file"}.issubset(narrate_options))

    def test_registers_sheet_gear_custom(self) -> None:
        command = self.bot.get_command("sheet gear custom")
        self.assertIsNotNone(command)
        self.assertIn("perso", command.aliases)

    def test_slash_descriptions_fit_discord_limit(self) -> None:
        for name, description in _walk_descriptions(self.bot.tree.get_commands()):
            self.assertLessEqual(len(description), 100, msg=name)


class TestDeleteCommandSlash(unittest.IsolatedAsyncioTestCase):
    async def test_defers_silent_slash_interactions(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.interaction.response.is_done.return_value = False
        ctx.defer = AsyncMock()
        ctx.interaction.delete_original_response = AsyncMock()
        ctx.message.delete = AsyncMock()
        await delete_command(ctx)
        ctx.defer.assert_awaited_once_with(ephemeral=True)
        ctx.interaction.delete_original_response.assert_awaited_once()
        ctx.message.delete.assert_not_called()


class TestRollArgumentOrder(unittest.IsolatedAsyncioTestCase):
    async def _parse_prefix_args(self, rest: str) -> dict:
        bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
        setup_roll(bot)
        command = bot.get_command("roll")
        ctx = SimpleNamespace(
            view=StringView(rest),
            message=SimpleNamespace(attachments=[]),
            command=command,
            interaction=None,
        )
        await command._parse_arguments(ctx)
        return ctx.kwargs

    async def test_prefix_skill_goes_to_args_not_member(self) -> None:
        kwargs = await self._parse_prefix_args("perception")
        self.assertEqual(kwargs["args"], "perception")
        self.assertNotIn("member", kwargs)

    async def test_prefix_keeps_advantage_in_args(self) -> None:
        kwargs = await self._parse_prefix_args("adv perception")
        self.assertEqual(kwargs["args"], "adv perception")
