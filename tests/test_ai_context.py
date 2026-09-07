import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from ai.context import (
    format_campaign_lore,
    format_history_line,
    gather_campaign_lore,
    gather_recent_messages,
    lore_query,
)
from campaign.lore import CampaignEntry


def _message(
    *,
    mid: int,
    author: str,
    content: str = "",
    attachments: list | None = None,
) -> MagicMock:
    item = MagicMock()
    item.id = mid
    item.author.display_name = author
    item.clean_content = content
    item.content = content
    item.attachments = attachments or []
    return item


class _History:
    def __init__(self, messages: list) -> None:
        self.messages = messages

    def __call__(self, *, limit: int):
        async def _iter():
            for message in self.messages[:limit]:
                yield message

        return _iter()


class TestFormatHistoryLine(unittest.TestCase):
    def test_skips_empty(self) -> None:
        self.assertIsNone(format_history_line(_message(mid=1, author="Aelric")))

    def test_keeps_plain_and_bot_lines(self) -> None:
        self.assertEqual(
            format_history_line(
                _message(mid=1, author="Orynn", content=";pc Bonsoir.")
            ),
            "Orynn: ;pc Bonsoir.",
        )
        self.assertEqual(
            format_history_line(
                _message(mid=2, author="Arkann", content="*La porte grince.*")
            ),
            "Arkann: *La porte grince.*",
        )

    def test_marks_images(self) -> None:
        line = format_history_line(
            _message(mid=3, author="Mira", attachments=[object()])
        )
        self.assertEqual(line, "Mira: [image]")


class TestGatherRecentMessages(unittest.IsolatedAsyncioTestCase):
    async def test_takes_last_twenty_oldest_first_skips_invoke(self) -> None:
        messages = [
            _message(mid=99, author="Me", content=";ai continue"),
            *[
                _message(mid=i, author="P", content=f"msg {i}")
                for i in range(25, 0, -1)
            ],
        ]
        ctx = MagicMock()
        ctx.message.id = 99
        ctx.channel.history = _History(messages)
        lines = await gather_recent_messages(ctx, limit=20)
        self.assertEqual(len(lines), 20)
        self.assertEqual(lines[0], "P: msg 6")
        self.assertEqual(lines[-1], "P: msg 25")
        self.assertTrue(all(";ai" not in line for line in lines))

    async def test_empty_without_history(self) -> None:
        ctx = MagicMock()
        ctx.channel = SimpleNamespace()
        ctx.message = None
        self.assertEqual(await gather_recent_messages(ctx, limit=20), [])


class TestCampaignLoreForAi(unittest.IsolatedAsyncioTestCase):
    def test_joins_query_chunks(self) -> None:
        self.assertEqual(lore_query("un orage", "Phandalin", ""), "un orage Phandalin")

    def test_formats_and_truncates_entries(self) -> None:
        text = format_campaign_lore(
            [
                CampaignEntry(
                    section="lieux",
                    title="Phandalin",
                    body="Petite ville minière.",
                    jump_url="https://discord.com/channels/1/100",
                    channel_id=100,
                    search_text="",
                ),
                CampaignEntry(
                    section="pnj",
                    title="Toblen",
                    body="A" * 800,
                    jump_url="https://discord.com/channels/1/111",
                    channel_id=111,
                    search_text="",
                ),
            ]
        )
        self.assertIn("lieux — Phandalin", text)
        self.assertIn("Petite ville minière.", text)
        self.assertIn("pnj — Toblen", text)
        self.assertTrue(text.endswith("…") or "…" in text)

    async def test_gather_selects_matching_entries(self) -> None:
        entries = [
            CampaignEntry(
                section="lieux",
                title="Phandalin",
                body="Petite ville.",
                jump_url="u",
                channel_id=1,
                search_text="lieux Phandalin Petite ville",
            )
        ]
        with patch(
            "ai.context.fetch_campaign_entries",
            new=AsyncMock(return_value=entries),
        ):
            lore = await gather_campaign_lore(SimpleNamespace(id=1), "Phandalin")
        self.assertIn("Phandalin", lore)
        self.assertIn("Petite ville.", lore)

    async def test_gather_skips_without_guild(self) -> None:
        self.assertEqual(await gather_campaign_lore(None, "Phandalin"), "")
