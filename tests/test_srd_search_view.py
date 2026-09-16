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

    async def test_subclass_uses_get_subclass(self) -> None:
        class _Select(SrdMatchSelect):
            @property
            def values(self) -> list[str]:
                return ["fighter/champion"]

        select = _Select(
            kind="subclass",
            matches=[
                {
                    "name": "Champion",
                    "slug": "fighter/champion",
                    "class_name": "Fighter",
                }
            ],
        )
        interaction = MagicMock()
        interaction.response.is_done.return_value = False
        interaction.response.defer = AsyncMock()
        embed = MagicMock()
        view = MagicMock()
        with (
            patch(
                "srd.search_view.fivetools.get_subclass",
                new_callable=AsyncMock,
                return_value=({"name": "Fighter"}, {"name": "Champion"}),
            ) as getter,
            patch(
                "srd.search_view.class_lookup_message",
                return_value=(embed, view),
            ),
            patch(
                "srd.search_view.send_interaction_message", new_callable=AsyncMock
            ) as send,
        ):
            await select.callback(interaction)
        interaction.response.defer.assert_awaited_once()
        getter.assert_awaited_once_with("fighter/champion")
        send.assert_awaited_once()
        self.assertTrue(send.await_args.kwargs.get("edit"))
        self.assertIs(send.await_args.kwargs.get("view"), view)
