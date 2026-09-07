import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.command_log import (
    LOG_CHANNEL_NAME,
    find_log_channel,
    format_command_invocation,
    inspect_log_channel,
    log_app_command,
    log_command,
)


class TestFormatCommandInvocation(unittest.TestCase):
    def test_prefix_uses_message_content(self) -> None:
        ctx = MagicMock()
        ctx.interaction = None
        ctx.command.qualified_name = "roll"
        ctx.message.content = ";roll 1d20"
        self.assertEqual(format_command_invocation(ctx), ";roll 1d20")

    def test_slash_formats_kwargs(self) -> None:
        ctx = MagicMock()
        ctx.interaction = MagicMock()
        ctx.command.qualified_name = "desc set"
        ctx.kwargs = {"text": "Phandalin"}
        self.assertEqual(
            format_command_invocation(ctx),
            "/desc set text: Phandalin",
        )


class TestFindLogChannel(unittest.TestCase):
    def test_finds_by_exact_name(self) -> None:
        channel = MagicMock()
        channel.name = LOG_CHANNEL_NAME
        guild = MagicMock()
        guild.text_channels = [channel]
        self.assertIs(find_log_channel(guild), channel)


class TestInspectLogChannel(unittest.TestCase):
    def test_warns_when_missing(self) -> None:
        guild = MagicMock()
        guild.name = "Potato Head"
        guild.id = 1
        guild.text_channels = []
        guild.me = MagicMock()
        with self.assertLogs("bot.command_log", level="WARNING") as logs:
            inspect_log_channel(guild)
        self.assertIn(LOG_CHANNEL_NAME, logs.output[0])


class TestLogCommand(unittest.IsolatedAsyncioTestCase):
    async def test_skips_when_log_channel_missing(self) -> None:
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 99
        ctx.guild.name = "Potato Head"
        ctx.guild.text_channels = []
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        with patch("bot.command_log.inspect_log_channel") as inspect:
            await log_command(ctx)
        inspect.assert_called_once_with(ctx.guild)

    async def test_posts_invocation(self) -> None:
        log_channel = MagicMock()
        log_channel.name = LOG_CHANNEL_NAME
        log_channel.send = AsyncMock()
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 1
        ctx.guild.text_channels = [log_channel]
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        ctx.interaction = None
        ctx.message.content = ";roll 1d20"
        ctx.channel.mention = "#blabla"
        ctx.author.display_name = "Fox"
        ctx.author.id = 42
        await log_command(ctx)
        log_channel.send.assert_awaited_once()
        self.assertIn(";roll 1d20", log_channel.send.await_args.args[0])

    async def test_retries_send_after_rate_limit(self) -> None:
        limited_response = MagicMock()
        limited_response.status = 429
        limited_response.reason = "Too Many Requests"
        limited_response.headers = {
            "Via": "1.1 google",
            "Retry-After": "0.1",
        }
        limited = discord.HTTPException(
            limited_response, {"message": "Too Many Requests"}
        )
        log_channel = MagicMock()
        log_channel.name = LOG_CHANNEL_NAME
        log_channel.send = AsyncMock(side_effect=[limited, None])
        ctx = MagicMock()
        ctx.guild = MagicMock()
        ctx.guild.id = 1
        ctx.guild.name = "Potato Head"
        ctx.guild.text_channels = [log_channel]
        ctx.command = MagicMock()
        ctx.command.qualified_name = "roll"
        ctx.interaction = None
        ctx.message.content = ";roll 1d20"
        ctx.channel.mention = "#blabla"
        ctx.author.display_name = "Fox"
        ctx.author.id = 42
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock):
            await log_command(ctx)
        self.assertEqual(log_channel.send.await_count, 2)


class TestLogAppCommand(unittest.IsolatedAsyncioTestCase):
    async def test_skips_hybrid_commands(self) -> None:
        interaction = MagicMock()
        interaction.guild = MagicMock()
        command = MagicMock()
        command.__commands_is_hybrid_app_command__ = True
        await log_app_command(interaction, command)

    async def test_logs_pure_slash(self) -> None:
        log_channel = MagicMock()
        log_channel.name = LOG_CHANNEL_NAME
        log_channel.send = AsyncMock()
        interaction = MagicMock()
        interaction.guild = MagicMock()
        interaction.guild.id = 1
        interaction.guild.name = "Potato Head"
        interaction.guild.text_channels = [log_channel]
        interaction.channel.mention = "#blabla"
        interaction.user.display_name = "Fox"
        interaction.user.id = 42
        interaction.namespace = (("topic", "sheet"),)
        command = MagicMock()
        command.name = "help"
        command.qualified_name = "help"
        await log_app_command(interaction, command)
        log_channel.send.assert_awaited_once()
        self.assertIn("/help topic: sheet", log_channel.send.await_args.args[0])
