import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.utils import time_snowflake

from bot.catchup import (
    _catch_up_channel,
    _catchup_after,
    _iter_catchup_channels,
    is_catchup_invoke,
    reset_session_tracking,
)


def _http_error(
    status: int,
    reason: str,
    *,
    headers: dict[str, str] | None = None,
) -> discord.HTTPException:
    response = MagicMock()
    response.status = status
    response.reason = reason
    response.headers = headers or {}
    return discord.HTTPException(response, {"message": reason})


def _message(
    *, message_id: int, content: str = "hello", bot: bool = False
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.id = message_id
    message.content = content
    message.author.bot = bot
    message.guild = MagicMock()
    message.channel.id = 42
    message.attachments = []
    return message


def _history(messages: list[MagicMock]):
    async def history(*, after=None, oldest_first=True, limit=200):
        items = list(messages)
        if after is not None:
            after_id = after.id if isinstance(after, discord.Object) else 0
            items = [item for item in items if item.id > after_id]
        if not oldest_first:
            items = list(reversed(items))
        for item in items[:limit]:
            yield item

    return history


def _text_channel(
    *, channel_id: int = 42, messages: list[MagicMock] | None = None
) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.guild = MagicMock()
    channel.guild.me = MagicMock()
    channel.parent = None
    perms = MagicMock()
    perms.view_channel = True
    perms.read_message_history = True
    channel.permissions_for.return_value = perms
    channel.history = _history(messages or [])
    channel.threads = []
    return channel


class TestCatchupSession(unittest.TestCase):
    def test_reset_session_tracking_clears_processed_ids(self) -> None:
        from bot import catchup

        catchup._processed_this_session.add(12345)
        reset_session_tracking()
        self.assertEqual(len(catchup._processed_this_session), 0)

    def test_is_catchup_invoke_reads_context_flag(self) -> None:
        ctx = type("Ctx", (), {})()
        self.assertFalse(is_catchup_invoke(ctx))
        ctx._from_catchup = True
        self.assertTrue(is_catchup_invoke(ctx))


class TestCatchupAfter(unittest.TestCase):
    def test_clamps_stale_last_ids_to_max_age(self) -> None:
        stale = time_snowflake(datetime.now(timezone.utc) - timedelta(days=20))
        after = _catchup_after(1, {"1": stale})
        self.assertIsInstance(after, datetime)
        age = datetime.now(timezone.utc) - after
        self.assertLess(age, timedelta(hours=73))

    def test_keeps_recent_last_id(self) -> None:
        recent = time_snowflake(datetime.now(timezone.utc) - timedelta(hours=1))
        after = _catchup_after(1, {"1": recent})
        self.assertIsInstance(after, discord.Object)
        self.assertEqual(after.id, recent)


class TestCatchupOrphanThreads(unittest.IsolatedAsyncioTestCase):
    async def test_skips_thread_with_missing_parent(self) -> None:
        channel = MagicMock(spec=discord.Thread)
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()
        channel.parent = None
        channel.permissions_for.side_effect = discord.ClientException(
            "Parent channel not found"
        )

        processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        channel.history.assert_not_called()

    async def test_reads_forum_threads(self) -> None:
        channel = MagicMock(spec=discord.Thread)
        channel.id = 42
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()
        channel.parent = MagicMock(spec=discord.ForumChannel)
        perms = MagicMock()
        perms.view_channel = True
        perms.read_message_history = True
        channel.permissions_for.return_value = perms
        channel.history = _history([_message(message_id=5, content="chat")])

        with patch("bot.catchup.mark_channel_message_processed") as mark:
            processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        mark.assert_called_with(channel_id=42, message_id=5)


class TestCatchupCursor(unittest.IsolatedAsyncioTestCase):
    async def test_advances_cursor_past_non_commands(self) -> None:
        messages = [
            _message(message_id=100 + index, content="chat") for index in range(5)
        ]
        channel = _text_channel(messages=messages)
        with patch("bot.catchup.mark_channel_message_processed") as mark:
            processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        mark.assert_called_with(channel_id=42, message_id=104)

    async def test_pages_beyond_first_window(self) -> None:
        messages = [
            _message(message_id=index + 1, content="chat") for index in range(3)
        ]
        channel = _text_channel(messages=messages)
        with (
            patch("bot.catchup.CATCHUP_MAX_MESSAGES", 2),
            patch("bot.catchup.mark_channel_message_processed") as mark,
        ):
            processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        mark.assert_called_with(channel_id=42, message_id=3)

    async def test_replays_every_command(self) -> None:
        reset_session_tracking()
        roll = _message(message_id=10, content=";roll 1d20")
        hp = _message(message_id=11, content=";hp -4")
        channel = _text_channel(messages=[roll, hp])

        bot = MagicMock()

        async def get_context(message):
            ctx = MagicMock()
            ctx.command = MagicMock()
            ctx.message = message
            return ctx

        bot.get_context = get_context
        bot.invoke = AsyncMock()

        with patch("bot.catchup.mark_channel_message_processed"):
            processed = await _catch_up_channel(bot, channel, last_ids={})
        self.assertEqual(processed, 2)
        self.assertEqual(bot.invoke.await_count, 2)

    async def test_failed_command_does_not_block_channel(self) -> None:
        reset_session_tracking()
        failed = _message(message_id=11, content=";roll 1d20")
        later = _message(message_id=12, content=";hp -4")
        channel = _text_channel(messages=[failed, later])

        bot = MagicMock()

        async def get_context(message):
            ctx = MagicMock()
            ctx.command = MagicMock()
            ctx.message = message
            return ctx

        async def invoke(ctx):
            if ctx.message.id == 11:
                raise RuntimeError("boom")

        bot.get_context = get_context
        bot.invoke = AsyncMock(side_effect=invoke)

        with (
            patch("bot.catchup.mark_channel_message_processed") as mark,
            self.assertLogs("bot.catchup", level="ERROR"),
        ):
            processed = await _catch_up_channel(bot, channel, last_ids={})
        self.assertEqual(processed, 2)
        mark.assert_called_with(channel_id=42, message_id=12)

    async def test_retries_history_after_rate_limit(self) -> None:
        messages = [_message(message_id=1, content="chat")]
        channel = _text_channel(messages=messages)
        original = channel.history
        calls = {"n": 0}
        limited = _http_error(
            429,
            "Too Many Requests",
            headers={"Via": "1.1 google", "Retry-After": "0.2"},
        )

        async def history(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise limited
            async for item in original(**kwargs):
                yield item

        channel.history = history
        with (
            patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock),
            patch("bot.catchup.mark_channel_message_processed") as mark,
        ):
            processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        self.assertEqual(calls["n"], 2)
        mark.assert_called_with(channel_id=42, message_id=1)

    async def test_stops_on_cloudflare_rate_limit(self) -> None:
        channel = _text_channel(messages=[_message(message_id=1, content="chat")])

        async def history(**kwargs):
            raise _http_error(429, "Too Many Requests")
            if False:
                yield None

        channel.history = history
        with patch("bot.catchup.mark_channel_message_processed") as mark:
            processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        mark.assert_not_called()


class TestCatchupSkips(unittest.IsolatedAsyncioTestCase):
    async def test_never_replays_purge(self) -> None:
        reset_session_tracking()
        purge = _message(message_id=20, content=";purge 20")
        channel = _text_channel(messages=[purge])
        bot = MagicMock()

        async def get_context(message):
            ctx = MagicMock()
            ctx.command = MagicMock()
            ctx.command.qualified_name = "purge"
            ctx.message = message
            return ctx

        bot.get_context = get_context
        bot.invoke = AsyncMock()
        with patch("bot.catchup.mark_channel_message_processed") as mark:
            processed = await _catch_up_channel(bot, channel, last_ids={})
        self.assertEqual(processed, 0)
        bot.invoke.assert_not_awaited()
        mark.assert_called_with(channel_id=42, message_id=20)

    async def test_skips_history_when_nothing_new(self) -> None:
        channel = _text_channel(messages=[_message(message_id=5, content=";roll")])
        channel.last_message_id = 5
        channel.history = MagicMock()
        processed = await _catch_up_channel(MagicMock(), channel, last_ids={"42": 5})
        self.assertEqual(processed, 0)
        channel.history.assert_not_called()


class TestCatchupChannelIter(unittest.IsolatedAsyncioTestCase):
    async def test_scans_forum_threads(self) -> None:
        text = MagicMock(spec=discord.TextChannel)
        text.id = 1
        text.threads = []

        async def no_archived(*, limit: int = 25):
            if False:
                yield None

        text.archived_threads = no_archived
        forum_thread = SimpleNamespace(id=99)
        forum = SimpleNamespace(threads=[forum_thread], archived_threads=no_archived)
        guild = SimpleNamespace(text_channels=[text], forums=[forum])

        channels = await _iter_catchup_channels(guild)  # type: ignore[arg-type]
        self.assertEqual([channel.id for channel in channels], [1, 99])

    async def test_skips_threads_archived_before_window(self) -> None:
        recent = SimpleNamespace(id=7, archive_timestamp=datetime.now(timezone.utc))
        old = SimpleNamespace(
            id=8, archive_timestamp=datetime.now(timezone.utc) - timedelta(days=30)
        )

        async def archived(*, limit: int = 25):
            yield recent
            yield old

        text = MagicMock(spec=discord.TextChannel)
        text.id = 1
        text.threads = []
        text.archived_threads = archived
        guild = SimpleNamespace(text_channels=[text], forums=[])

        channels = await _iter_catchup_channels(guild)  # type: ignore[arg-type]
        self.assertEqual([channel.id for channel in channels], [1, 7])


if __name__ == "__main__":
    unittest.main()
