import unittest
from unittest.mock import AsyncMock, MagicMock

import discord

from sheets.context import parse_mention_and_text, resolve_owner


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
        with unittest.mock.patch("sheets.context.command_reply", new=AsyncMock()) as reply:
            owner_id = await resolve_owner(ctx, member)
        self.assertIsNone(owner_id)
        reply.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
