import unittest
from unittest.mock import AsyncMock, MagicMock

from bot.slash_globals import purge_stale_global_app_commands


class TestPurgeStaleGlobalAppCommands(unittest.IsolatedAsyncioTestCase):
    async def test_skips_entry_point_and_deletes_the_rest(self) -> None:
        bot = MagicMock()
        bot.application_id = 99
        bot.http.get_global_commands = AsyncMock(
            return_value=[
                {"id": "1", "name": "desc", "type": 1},
                {"id": "2", "name": "launch", "type": 4},
                {"id": "3", "name": "roll", "type": 1},
            ]
        )
        bot.http.delete_global_command = AsyncMock()

        removed = await purge_stale_global_app_commands(bot)

        self.assertEqual(removed, 2)
        bot.http.delete_global_command.assert_any_call(99, "1")
        bot.http.delete_global_command.assert_any_call(99, "3")
        self.assertEqual(bot.http.delete_global_command.await_count, 2)

    async def test_no_app_id_is_noop(self) -> None:
        bot = MagicMock(application_id=None)
        bot.http.get_global_commands = AsyncMock()
        removed = await purge_stale_global_app_commands(bot)
        self.assertEqual(removed, 0)
        bot.http.get_global_commands.assert_not_called()
