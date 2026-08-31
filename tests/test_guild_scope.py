import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.events import leave_if_foreign


class TestLeaveIfForeign(unittest.IsolatedAsyncioTestCase):
    async def test_leaves_other_servers(self) -> None:
        guild = SimpleNamespace(id=22, name="Le Moulin", leave=AsyncMock())
        with patch("bot.events.is_home_guild", return_value=False):
            left = await leave_if_foreign(guild)
        self.assertTrue(left)
        guild.leave.assert_awaited_once()

    async def test_keeps_home_server(self) -> None:
        guild = SimpleNamespace(id=11, name="Potato Head", leave=AsyncMock())
        with patch("bot.events.is_home_guild", return_value=True):
            left = await leave_if_foreign(guild)
        self.assertFalse(left)
        guild.leave.assert_not_called()
