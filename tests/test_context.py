import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from sheets.context import infer_player_id, parse_mention_and_text, resolve_owner


class TestParseMentionAndText(unittest.TestCase):
    def test_keeps_item_name_when_not_a_mention(self) -> None:
        ctx = MagicMock()
        ctx.message.mentions = []
        member, text = parse_mention_and_text(ctx, "dagger")
        self.assertIsNone(member)
        self.assertEqual(text, "dagger")

    def test_strips_player_mention(self) -> None:
        ctx = MagicMock()
        player = MagicMock(spec=discord.Member)
        ctx.message.mentions = [player]
        member, text = parse_mention_and_text(ctx, "<@123> dagger")
        self.assertIs(member, player)
        self.assertEqual(text, "dagger")

    def test_resolves_raw_mention_from_text(self) -> None:
        player = MagicMock(spec=discord.Member)
        ctx = MagicMock()
        ctx.message.mentions = []
        ctx.guild.get_member.return_value = player
        member, text = parse_mention_and_text(ctx, "<@123> dagger")
        self.assertIs(member, player)
        self.assertEqual(text, "dagger")
        ctx.guild.get_member.assert_called_once_with(123)


class TestResolveOwner(unittest.IsolatedAsyncioTestCase):
    async def test_self_mention_does_not_require_admin(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 42
        ctx.author.guild_permissions.administrator = False
        ctx.author.guild_permissions.manage_guild = False

        member = MagicMock(spec=discord.Member)
        member.id = 42

        owner_id = await resolve_owner(ctx, member)
        self.assertEqual(owner_id, 42)

    async def test_other_member_requires_admin(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.guild_permissions.administrator = False
        ctx.author.guild_permissions.manage_guild = False

        member = MagicMock(spec=discord.Member)
        member.id = 2

        ctx.reply = AsyncMock()
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.owner_id = 99
        with unittest.mock.patch("bot.privacy.command_reply", new=AsyncMock()) as reply:
            owner_id = await resolve_owner(ctx, member)
        self.assertIsNone(owner_id)
        reply.assert_awaited_once()
        self.assertIn(
            "fiche d’un autre joueur", reply.await_args.args[1]
        )

    async def test_staff_without_mention_uses_player_section(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.name = "Orynn"
        ctx.author.display_name = "Orynn"
        ctx.author.global_name = "Orynn"
        ctx.author.nick = None
        ctx.author.guild_permissions.administrator = True
        ctx.author.guild_permissions.manage_guild = True
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.owner_id = 1

        with unittest.mock.patch("sheets.context.infer_player_id", return_value=99):
            owner_id = await resolve_owner(ctx, None)
        self.assertEqual(owner_id, 99)

    async def test_staff_without_target_asks_for_player(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.name = "Orynn"
        ctx.author.display_name = "Orynn"
        ctx.author.global_name = "Orynn"
        ctx.author.nick = None
        ctx.author.guild_permissions.administrator = True
        ctx.author.guild_permissions.manage_guild = True
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.owner_id = 1

        with unittest.mock.patch("sheets.context.infer_player_id", return_value=None):
            with unittest.mock.patch(
                "sheets.context.command_reply", new=AsyncMock()
            ) as reply:
                owner_id = await resolve_owner(ctx, None)
        self.assertIsNone(owner_id)
        reply.assert_awaited_once()
        self.assertIn("sa section", reply.await_args.args[1])

    async def test_staff_self_mention_uses_player_section(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.name = "Orynn"
        ctx.author.display_name = "Orynn"
        ctx.author.global_name = "Orynn"
        ctx.author.nick = None
        ctx.author.guild_permissions.administrator = True
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.owner_id = 1
        member = MagicMock(spec=discord.Member)
        member.id = 1

        with unittest.mock.patch("sheets.context.infer_player_id", return_value=77):
            owner_id = await resolve_owner(ctx, member)
        self.assertEqual(owner_id, 77)

    async def test_staff_in_trash_uses_mock_sheet(self) -> None:
        ctx = MagicMock()
        ctx.author = MagicMock(spec=discord.Member)
        ctx.author.id = 1
        ctx.author.name = "Orynn"
        ctx.author.display_name = "Orynn"
        ctx.author.global_name = "Orynn"
        ctx.author.nick = None
        ctx.author.guild_permissions.administrator = True
        ctx.author.guild_permissions.manage_guild = True
        ctx.guild = MagicMock(spec=discord.Guild)
        ctx.guild.id = 7
        ctx.guild.owner_id = 1
        ctx.channel = MagicMock()
        ctx.channel.name = "🚯trash"
        ctx.channel.id = 404

        with unittest.mock.patch(
            "sheets.context.ensure_sandbox_sheet"
        ) as ensure:
            self.assertEqual(infer_player_id(ctx), -404)
            owner_id = await resolve_owner(ctx, None)
        self.assertEqual(owner_id, -404)
        ensure.assert_called()


if __name__ == "__main__":
    unittest.main()
