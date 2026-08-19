import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord.errors import Forbidden, NotFound

from bot.command_helpers import command_reply, delete_command


class TestCommandReply(unittest.IsolatedAsyncioTestCase):
    async def test_can_disable_linkify_and_definition_menu(self) -> None:
        ctx = MagicMock()
        with patch("bot.command_helpers.send_reply", new=AsyncMock()) as send_reply:
            await command_reply(
                ctx,
                "Something went wrong running that command.",
                linkify=False,
                definition_menu=False,
            )
        send_reply.assert_awaited_once_with(
            ctx,
            "Something went wrong running that command.",
            linkify=False,
            definition_menu=False,
        )


class TestDeleteCommand(unittest.IsolatedAsyncioTestCase):
    async def test_ignores_forbidden(self) -> None:
        ctx = MagicMock()
        ctx.interaction = None
        ctx.channel.id = 1
        ctx.message.id = 2
        ctx.message.delete = AsyncMock(side_effect=Forbidden(MagicMock(), "no perms"))
        await delete_command(ctx)

    async def test_ignores_timeout(self) -> None:
        ctx = MagicMock()
        ctx.interaction = None
        ctx.channel.id = 1
        ctx.message.id = 2
        ctx.message.delete = AsyncMock(side_effect=TimeoutError)
        await delete_command(ctx)

    async def test_ignores_not_found(self) -> None:
        ctx = MagicMock()
        ctx.interaction = None
        ctx.channel.id = 1
        ctx.message.id = 2
        ctx.message.delete = AsyncMock(side_effect=NotFound(MagicMock(), "gone"))
        await delete_command(ctx)
