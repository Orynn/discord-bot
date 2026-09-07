import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.purge_commands import (
    PurgeConfirmView,
    _count_label,
    _is_bulk_deletable,
    _resolve_purge_channel,
    estimate_message_count,
    prompt_channel_purge,
    purge_messages,
)


class TestPurgeHelpers(unittest.TestCase):
    def test_skips_messages_older_than_14_days(self) -> None:
        recent = MagicMock()
        recent.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        old = MagicMock()
        old.created_at = datetime.now(timezone.utc) - timedelta(days=20)
        self.assertTrue(_is_bulk_deletable(recent))
        self.assertFalse(_is_bulk_deletable(old))

    def test_count_label(self) -> None:
        self.assertEqual(_count_label(0), "aucun")
        self.assertEqual(_count_label(1), "1 message")
        self.assertEqual(_count_label(3), "3 messages")
        self.assertEqual(_count_label(501), "plus de 500")


class TestEstimateMessageCount(unittest.IsolatedAsyncioTestCase):
    async def test_counts_history(self) -> None:
        channel = MagicMock()

        async def history(*, limit, before=None):
            for _ in range(3):
                yield MagicMock()

        channel.history = history
        self.assertEqual(await estimate_message_count(channel), 3)

    async def test_unsupported_channel(self) -> None:
        self.assertEqual(await estimate_message_count(object()), 0)


class TestPurgeMessages(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_to_channel_purge(self) -> None:
        channel = MagicMock()
        channel.purge = AsyncMock(return_value=["a", "b"])
        deleted = await purge_messages(channel, before=MagicMock())
        channel.purge.assert_awaited_once_with(
            limit=50,
            before=channel.purge.await_args.kwargs["before"],
            oldest_first=False,
            check=_is_bulk_deletable,
        )
        self.assertEqual(deleted, ["a", "b"])

    async def test_waits_and_retries_discord_rate_limit(self) -> None:
        response = MagicMock()
        response.status = 429
        response.reason = "Too Many Requests"
        response.headers = {}
        limited = discord.HTTPException(
            response, {"message": "You are being rate limited."}
        )
        channel = MagicMock()
        channel.purge = AsyncMock(side_effect=[limited, ["a"]])
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock) as sleep:
            deleted = await purge_messages(channel, before=MagicMock())
        self.assertEqual(deleted, ["a"])
        self.assertEqual(channel.purge.await_count, 2)
        sleep.assert_awaited()


class TestPurgeConfirmView(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_other_users(self) -> None:
        view = PurgeConfirmView(invoker_id=1, channel_id=10)
        interaction = MagicMock()
        interaction.user.id = 2
        interaction.response.send_message = AsyncMock()
        self.assertFalse(await view.interaction_check(interaction))
        interaction.response.send_message.assert_awaited_once()

    async def test_accepts_invoker(self) -> None:
        view = PurgeConfirmView(invoker_id=1, channel_id=10)
        interaction = MagicMock()
        interaction.user.id = 1
        self.assertTrue(await view.interaction_check(interaction))

    async def test_confirm_acks_then_purges_guild_channel(self) -> None:
        view = PurgeConfirmView(invoker_id=1, channel_id=10)
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.purge = AsyncMock(return_value=[MagicMock(), MagicMock()])
        interaction = MagicMock()
        interaction.user.id = 1
        interaction.guild.get_channel.return_value = channel
        interaction.guild.get_thread.return_value = None
        interaction.client.get_channel.return_value = None
        interaction.channel = MagicMock()
        interaction.channel.id = 10
        interaction.channel.purge = None
        prompt = MagicMock()
        prompt.delete = AsyncMock()
        interaction.message = prompt
        interaction.response.edit_message = AsyncMock()

        with patch(
            "bot.purge_commands.estimate_message_count",
            new=AsyncMock(return_value=0),
        ):
            await view.confirm.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        self.assertIn(
            "Purge en cours",
            interaction.response.edit_message.await_args.kwargs["content"],
        )
        channel.purge.assert_awaited_once()
        prompt.delete.assert_awaited_once()

    async def test_confirm_reports_old_messages_left(self) -> None:
        view = PurgeConfirmView(invoker_id=1, channel_id=10)
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.purge = AsyncMock(return_value=[MagicMock()])
        interaction = MagicMock()
        interaction.guild.get_channel.return_value = channel
        interaction.guild.get_thread.return_value = None
        interaction.client.get_channel.return_value = None
        interaction.channel = channel
        prompt = MagicMock()
        prompt.delete = AsyncMock()
        interaction.message = prompt
        interaction.response.edit_message = AsyncMock()
        view._edit_prompt = AsyncMock()

        with patch(
            "bot.purge_commands.estimate_message_count",
            new=AsyncMock(return_value=3),
        ):
            await view.confirm.callback(interaction)

        prompt.delete.assert_not_awaited()
        view._edit_prompt.assert_awaited()
        self.assertIn("14 jours", view._edit_prompt.await_args.args[1])


class TestResolvePurgeChannel(unittest.TestCase):
    def test_prefers_guild_text_channel(self) -> None:
        channel = MagicMock(spec=discord.TextChannel)
        channel.purge = AsyncMock()
        interaction = MagicMock()
        interaction.guild.get_channel.return_value = channel
        interaction.channel = MagicMock()
        self.assertIs(_resolve_purge_channel(interaction, 10), channel)


class TestPromptChannelPurge(unittest.IsolatedAsyncioTestCase):
    async def test_reports_empty_channel(self) -> None:
        ctx = MagicMock()
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 10
        ctx.channel.mention = "#salon"
        ctx.channel.guild = MagicMock()
        ctx.channel.guild.me = MagicMock()
        ctx.channel.permissions_for.return_value.manage_messages = True
        ctx.channel.permissions_for.return_value.read_message_history = True
        ctx.interaction = None
        ctx.message = MagicMock()
        with (
            patch(
                "bot.purge_commands.estimate_message_count",
                new=AsyncMock(return_value=0),
            ),
            patch("bot.purge_commands.command_reply", new_callable=AsyncMock) as reply,
            patch("bot.purge_commands.delete_command", new_callable=AsyncMock),
        ):
            await prompt_channel_purge(ctx)
        reply.assert_awaited_once()
        self.assertIn("Aucun message", reply.await_args.args[1])

    async def test_sends_confirmation_when_messages_exist(self) -> None:
        ctx = MagicMock()
        ctx.author.id = 42
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 10
        ctx.channel.mention = "#salon"
        ctx.channel.guild = MagicMock()
        ctx.channel.guild.me = MagicMock()
        ctx.channel.permissions_for.return_value.manage_messages = True
        ctx.channel.permissions_for.return_value.read_message_history = True
        ctx.interaction = None
        ctx.message = MagicMock()
        sent = MagicMock()
        with (
            patch(
                "bot.purge_commands.estimate_message_count",
                new=AsyncMock(return_value=2),
            ),
            patch(
                "bot.purge_commands.send_message",
                new=AsyncMock(return_value=sent),
            ) as send,
            patch("bot.purge_commands.delete_command", new_callable=AsyncMock),
        ):
            await prompt_channel_purge(ctx)
        send.assert_awaited_once()
        view = send.await_args.kwargs["view"]
        self.assertIsInstance(view, PurgeConfirmView)
        self.assertEqual(view.invoker_id, 42)
        self.assertIs(view.message, sent)

    async def test_defers_slash_before_scanning(self) -> None:
        ctx = MagicMock()
        ctx.author.id = 42
        ctx.channel = MagicMock(spec=discord.TextChannel)
        ctx.channel.id = 10
        ctx.channel.mention = "#salon"
        ctx.channel.guild = MagicMock()
        ctx.channel.guild.me = MagicMock()
        ctx.channel.permissions_for.return_value.manage_messages = True
        ctx.channel.permissions_for.return_value.read_message_history = True
        ctx.interaction = MagicMock()
        ctx.interaction.response.is_done.return_value = False
        ctx.defer = AsyncMock()
        ctx.message = MagicMock()
        with (
            patch(
                "bot.purge_commands.estimate_message_count",
                new=AsyncMock(return_value=1),
            ),
            patch(
                "bot.purge_commands.send_interaction_message",
                new=AsyncMock(return_value=MagicMock()),
            ) as send,
            patch("bot.purge_commands.delete_command", new_callable=AsyncMock),
        ):
            await prompt_channel_purge(ctx)
        ctx.defer.assert_awaited_once()
        send.assert_awaited_once()
        self.assertTrue(send.await_args.kwargs.get("edit"))
        self.assertIsInstance(send.await_args.kwargs["view"], PurgeConfirmView)
