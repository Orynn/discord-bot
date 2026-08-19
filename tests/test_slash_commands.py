import unittest
from unittest.mock import AsyncMock, MagicMock

import discord
from discord.ext import commands

from bot.command_helpers import delete_command
from bot.help_commands import setup_help
from bot.slash import setup_slash
from bot.tree_utils import clamp_app_command_descriptions
from campaign.commands import setup_campaign
from combat.commands import setup_combat
from initiative.commands import setup_initiative
from npc.commands import setup_npc
from party.commands import setup_party
from pc.commands import setup_pc
from players.commands import setup_player
from roll.commands import setup_roll
from scene.commands import setup_desc
from sheets.commands import setup_sheet
from srd.commands import setup_srd


def _register_commands(bot: commands.Bot) -> None:
    for setup in (
        setup_npc,
        setup_desc,
        setup_pc,
        setup_roll,
        setup_sheet,
        setup_initiative,
        setup_party,
        setup_player,
        setup_srd,
        setup_campaign,
        setup_combat,
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
            {"help", "aide", "roll", "sheet", "combat", "init", "srd", "pc", "desc", "campaign"}.issubset(names)
        )
        campaign = next(command for command in self.bot.tree.get_commands() if command.name == "campaign")
        child_names = {child.name for child in campaign.commands}
        self.assertTrue(
            {"search", "post", "forum", "wiki", "import", "channels", "audit", "move", "repair"}.issubset(
                child_names
            )
        )
        import_cmd = next(child for child in campaign.commands if child.name == "import")
        option_names = {option.name for option in import_cmd.parameters}
        self.assertIn("query", option_names)
        self.assertIn("liens", option_names)

    def test_slash_descriptions_fit_discord_limit(self) -> None:
        for name, description in _walk_descriptions(self.bot.tree.get_commands()):
            self.assertLessEqual(len(description), 100, msg=name)


class TestDeleteCommandSlash(unittest.IsolatedAsyncioTestCase):
    async def test_skips_slash_interactions(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.message.delete = AsyncMock()
        await delete_command(ctx)
        ctx.message.delete.assert_not_called()
