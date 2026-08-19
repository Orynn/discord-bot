import unittest
from unittest.mock import MagicMock

import discord

from bot.catchup import CATCHUP_BLOCKED_COMMANDS, _is_catchup_allowed
from bot.checks import is_admin
from sheets.data import CharacterSheet, hit_die_sides
from sheets.dice import parse_roll_args, validate_roll_request


class TestIsAdmin(unittest.TestCase):
    def test_returns_false_in_dm(self) -> None:
        ctx = MagicMock()
        ctx.guild = None
        ctx.author = MagicMock(spec=discord.User)
        self.assertFalse(is_admin(ctx))

    def test_returns_true_for_admin_member(self) -> None:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.owner_id = 999
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.guild_permissions.administrator = True
        ctx.author.guild_permissions.manage_guild = False
        self.assertTrue(is_admin(ctx))

    def test_returns_true_for_guild_owner(self) -> None:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.owner_id = 42
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 42
        ctx.author.guild_permissions.administrator = False
        ctx.author.guild_permissions.manage_guild = False
        self.assertTrue(is_admin(ctx))

    def test_returns_true_for_manage_guild(self) -> None:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.owner_id = 999
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.guild_permissions.administrator = False
        ctx.author.guild_permissions.manage_guild = True
        self.assertTrue(is_admin(ctx))


class TestCatchupAllowlist(unittest.TestCase):
    def test_blocks_destructive_commands(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "sheet delete"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_attachment_commands(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = [MagicMock()]
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_allows_roll(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        self.assertTrue(_is_catchup_allowed(ctx))

    def test_blocks_campaign_subcommands(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "campaign import"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_sheet_money_add(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "sheet money add"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_init_add(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "init add"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_sheet_create(self) -> None:
        self.assertIn("sheet create", CATCHUP_BLOCKED_COMMANDS)


class TestRollValidation(unittest.TestCase):
    def test_rejects_advantage_on_non_d20(self) -> None:
        request = parse_roll_args("adv 2d6")
        with self.assertRaises(ValueError):
            validate_roll_request(request)

    def test_allows_advantage_on_d20(self) -> None:
        request = parse_roll_args("adv 1d20 athletics")
        validate_roll_request(request)


class TestHitDie(unittest.TestCase):
    def test_barbarian_uses_d12(self) -> None:
        sheet = CharacterSheet(name="Test", char_class="Barbarian")
        self.assertEqual(sheet.get_hit_die_sides(), 12)

    def test_unknown_class_defaults_to_d8(self) -> None:
        self.assertEqual(hit_die_sides(""), 8)


if __name__ == "__main__":
    unittest.main()
