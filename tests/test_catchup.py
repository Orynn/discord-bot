import unittest
from unittest.mock import MagicMock

import discord

from bot.catchup import _catch_up_channel, is_catchup_invoke, reset_session_tracking


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


class TestCatchupOrphanThreads(unittest.IsolatedAsyncioTestCase):
    async def test_skips_thread_with_missing_parent(self) -> None:
        channel = MagicMock(spec=discord.Thread)
        channel.guild = MagicMock()
        channel.guild.me = MagicMock()
        channel.parent = None
        channel.permissions_for.side_effect = discord.ClientException("Parent channel not found")

        processed = await _catch_up_channel(MagicMock(), channel, last_ids={})
        self.assertEqual(processed, 0)
        channel.history.assert_not_called()


if __name__ == "__main__":
    unittest.main()
