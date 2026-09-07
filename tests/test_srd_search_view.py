import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from srd.search_view import SrdMatchSelect


class TestSrdMatchSelect(unittest.IsolatedAsyncioTestCase):
    async def test_defers_before_lookup(self) -> None:
        class _Select(SrdMatchSelect):
            @property
            def values(self) -> list[str]:
                return ["goblin"]

        select = _Select(
            kind="monster",
            matches=[{"name": "Goblin", "slug": "goblin", "source": "XMM"}],
        )
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        getter = AsyncMock(return_value={"name": "Goblin"})
        embed = MagicMock()
        with (
            patch.dict(
                "srd.search_view._KIND_PRESENTERS",
                {"monster": (getter, lambda _item: embed)},
            ),
            patch(
                "srd.search_view.send_interaction_message", new_callable=AsyncMock
            ) as send,
        ):
            await select.callback(interaction)
        interaction.response.defer.assert_awaited_once()
        getter.assert_awaited_once_with("goblin")
        send.assert_awaited_once()
        self.assertTrue(send.await_args.kwargs.get("edit"))
