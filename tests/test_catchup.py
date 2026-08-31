import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import discord
from discord.utils import time_snowflake

from bot.catchup import (
    _catch_up_channel,
    _catchup_after,
    _iter_catchup_channels,
    is_catchup_invoke,
    reset_session_tracking,
)


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

    async def test_skips_forum_threads(self) -> None:
        channel = MagicMock(spec=discord.Thread)
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()
        channel.parent = MagicMock(spec=discord.ForumChannel)

        processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        channel.history.assert_not_called()


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


class TestCatchupChannelIter(unittest.IsolatedAsyncioTestCase):
    async def test_does_not_scan_forum_threads(self) -> None:
        text = MagicMock(spec=discord.TextChannel)
        text.id = 1
        text.threads = []

        async def no_archived(*, limit: int = 25):
            if False:
                yield None

        text.archived_threads = no_archived
        forum_thread = SimpleNamespace(id=99)
        forum = SimpleNamespace(threads=[forum_thread])
        guild = SimpleNamespace(text_channels=[text], forums=[forum])

        channels = await _iter_catchup_channels(guild)  # type: ignore[arg-type]
        self.assertEqual([channel.id for channel in channels], [1])


if __name__ == "__main__":
    unittest.main()
