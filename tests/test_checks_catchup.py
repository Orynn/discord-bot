import unittest
from unittest.mock import MagicMock, patch

import discord

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
