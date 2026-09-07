import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord.errors import Forbidden, NotFound

from bot.command_helpers import command_reply, defer_if_slash, delete_command


class TestDeferIfSlash(unittest.IsolatedAsyncioTestCase):
    async def test_defers_pending_slash(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.interaction.response.is_done.return_value = False
        ctx.defer = AsyncMock()
        await defer_if_slash(ctx)
        ctx.defer.assert_awaited_once_with(ephemeral=False)

    async def test_skips_prefix_commands(self) -> None:
        ctx = MagicMock()
        ctx.interaction = None
        ctx.defer = AsyncMock()
        await defer_if_slash(ctx)
        ctx.defer.assert_not_awaited()


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

    async def test_defers_pending_slash_interaction(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.interaction.response.is_done.return_value = False
        ctx.defer = AsyncMock()
        ctx.interaction.delete_original_response = AsyncMock()
        await delete_command(ctx)
        ctx.defer.assert_awaited_once_with(ephemeral=True)
        ctx.interaction.delete_original_response.assert_awaited_once()
        ctx.message.delete.assert_not_called()

    async def test_skips_delete_when_slash_already_answered(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.interaction.response.is_done.return_value = True
        ctx.defer = AsyncMock()
        ctx.interaction.delete_original_response = AsyncMock()
        await delete_command(ctx)
        ctx.defer.assert_not_awaited()
        ctx.interaction.delete_original_response.assert_not_awaited()
