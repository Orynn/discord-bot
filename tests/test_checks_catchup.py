import unittest
from unittest.mock import MagicMock, patch

import discord

from bot.catchup import CATCHUP_ALLOWED_COMMANDS, _is_catchup_allowed
from bot.checks import is_admin, is_admin_member, is_staff_member
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

    def test_resolves_user_to_cached_member(self) -> None:
        guild = MagicMock()
        guild.owner_id = 999
        member = MagicMock(spec=discord.Member)
        member.id = 7
        member.guild_permissions.administrator = True
        member.guild_permissions.manage_guild = False
        guild.get_member.return_value = member
        user = MagicMock(spec=discord.User)
        user.id = 7
        self.assertTrue(is_admin_member(guild, user))
        guild.get_member.assert_called_with(7)


class TestIsStaff(unittest.TestCase):
    def test_nick_does_not_grant_staff(self) -> None:
        guild = MagicMock()
        guild.owner_id = 1
        member = MagicMock(spec=discord.Member)
        member.id = 99
        member.name = "Orynn"
        member.display_name = "Orynn"
        member.global_name = "Orynn"
        member.nick = "Orynn"
        member.guild_permissions.administrator = False
        member.guild_permissions.manage_guild = False
        guild.get_member.return_value = member
        self.assertFalse(is_staff_member(guild, member))

    def test_staff_user_id_grants_staff(self) -> None:
        guild = MagicMock()
        guild.owner_id = 1
        member = MagicMock(spec=discord.Member)
        member.id = 42
        member.guild_permissions.administrator = False
        member.guild_permissions.manage_guild = False
        with patch("bot.checks.STAFF_USER_IDS", {42}):
            self.assertTrue(is_staff_member(guild, member))


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

    def test_blocks_roll(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        self.assertFalse(_is_catchup_allowed(ctx))
        ctx.command.qualified_name = "r"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_sheet_status(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "sheet status"
        self.assertFalse(_is_catchup_allowed(ctx))
        ctx.command.qualified_name = "status"
        self.assertFalse(_is_catchup_allowed(ctx))
        self.assertNotIn("status", CATCHUP_ALLOWED_COMMANDS)
        self.assertNotIn("sheet status", CATCHUP_ALLOWED_COMMANDS)

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

    def test_blocks_combat_play(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "combat play"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_sheet_gear_add(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "sheet gear add"
        self.assertFalse(_is_catchup_allowed(ctx))

    def test_blocks_sheet_create(self) -> None:
        self.assertNotIn("sheet create", CATCHUP_ALLOWED_COMMANDS)

    def test_blocks_image_generation(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "image"
        self.assertFalse(_is_catchup_allowed(ctx))
        self.assertNotIn("image", CATCHUP_ALLOWED_COMMANDS)

    def test_blocks_scene_and_whisper(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "scene set"
        self.assertFalse(_is_catchup_allowed(ctx))
        ctx.command.qualified_name = "whisper"
        self.assertFalse(_is_catchup_allowed(ctx))
        ctx.command.qualified_name = "arrive"
        self.assertFalse(_is_catchup_allowed(ctx))
        self.assertNotIn("whisper", CATCHUP_ALLOWED_COMMANDS)
        self.assertNotIn("scene", CATCHUP_ALLOWED_COMMANDS)
        self.assertNotIn("ai", CATCHUP_ALLOWED_COMMANDS)
        self.assertNotIn("desc", CATCHUP_ALLOWED_COMMANDS)

    def test_allows_idempotent_lookups(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.message.content = ""
        ctx.invoked_with = ""
        for name in (
            "help",
            "srd",
            "srd spell",
            "sheet show",
            "init show",
            "combat historique",
        ):
            ctx.command.qualified_name = name
            self.assertTrue(_is_catchup_allowed(ctx), msg=name)

    def test_blocks_combat_board(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.message.content = ";combat board"
        ctx.command = MagicMock()
        ctx.command.qualified_name = "combat board"
        self.assertFalse(_is_catchup_allowed(ctx))
        self.assertNotIn("combat board", CATCHUP_ALLOWED_COMMANDS)

    def test_allows_time_show_not_advance(self) -> None:
        ctx = MagicMock()
        ctx.message.attachments = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "time"
        ctx.invoked_with = "time"
        ctx.message.content = ";time"
        self.assertTrue(_is_catchup_allowed(ctx))
        ctx.message.content = ";time show"
        self.assertTrue(_is_catchup_allowed(ctx))
        ctx.invoked_with = "clock"
        ctx.message.content = ";clock"
        self.assertTrue(_is_catchup_allowed(ctx))
        ctx.invoked_with = "time"
        ctx.message.content = ";time 2h"
        self.assertFalse(_is_catchup_allowed(ctx))
        ctx.command.qualified_name = "time advance"
        ctx.message.content = ";time advance 2h"
        self.assertFalse(_is_catchup_allowed(ctx))


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
