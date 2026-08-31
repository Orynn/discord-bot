import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.speech import parenthetical_only_narration
from scene.commands import (
    _format_description,
    collect_desc_images,
    is_image_attachment,
    maybe_send_parenthetical_desc,
)


def _attachment(
    *,
    aid: int,
    filename: str,
    content_type: str | None,
) -> MagicMock:
    item = MagicMock()
    item.id = aid
    item.filename = filename
    item.content_type = content_type
    item.to_file = AsyncMock(return_value=f"file-{aid}")
    return item


class TestDescFormatting(unittest.TestCase):
    def test_italicizes_and_adds_period(self) -> None:
        self.assertEqual(
            _format_description("Rain on the docks", guild_id=0), "*Rain on the docks.*"
        )

    def test_empty_text_stays_empty(self) -> None:
        self.assertEqual(_format_description("   ", guild_id=0), "")


class TestParentheticalOnlyNarration(unittest.TestCase):
    def test_single_action_becomes_narration(self) -> None:
        self.assertEqual(
            parenthetical_only_narration("(ouvre la porte)"),
            "ouvre la porte",
        )
        self.assertEqual(parenthetical_only_narration("  (sourire)  "), "sourire")

    def test_multiple_parentheticals_join(self) -> None:
        self.assertEqual(
            parenthetical_only_narration("(s'approche) (silence)"),
            "s'approche silence",
        )

    def test_dialogue_keeps_speech(self) -> None:
        self.assertIsNone(parenthetical_only_narration("(sourire) Bonjour"))
        self.assertIsNone(parenthetical_only_narration("Bonjour"))
        self.assertIsNone(parenthetical_only_narration(""))


class TestMaybeSendParentheticalDesc(unittest.IsolatedAsyncioTestCase):
    async def test_routes_action_only_to_desc(self) -> None:
        ctx = MagicMock()
        with patch(
            "scene.commands.send_scene_description", new_callable=AsyncMock
        ) as send:
            routed = await maybe_send_parenthetical_desc(ctx, "(ouvre la porte)")
        self.assertTrue(routed)
        send.assert_awaited_once_with(ctx, "ouvre la porte")

    async def test_leaves_dialogue_alone(self) -> None:
        ctx = MagicMock()
        with patch(
            "scene.commands.send_scene_description", new_callable=AsyncMock
        ) as send:
            routed = await maybe_send_parenthetical_desc(ctx, "(sourire) Bonjour")
        self.assertFalse(routed)
        send.assert_not_awaited()


class TestDescImages(unittest.IsolatedAsyncioTestCase):
    def test_accepts_image_types(self) -> None:
        self.assertTrue(
            is_image_attachment(
                _attachment(aid=1, filename="scene.png", content_type="image/png")
            )
        )
        self.assertTrue(
            is_image_attachment(
                _attachment(aid=2, filename="shot.JPG", content_type=None)
            )
        )
        self.assertFalse(
            is_image_attachment(
                _attachment(aid=3, filename="notes.pdf", content_type="application/pdf")
            )
        )

    async def test_collects_unique_images_only(self) -> None:
        png = _attachment(aid=1, filename="a.png", content_type="image/png")
        pdf = _attachment(aid=2, filename="b.pdf", content_type="application/pdf")
        gif = _attachment(aid=3, filename="c.gif", content_type="image/gif")
        ctx = MagicMock()
        ctx.message.attachments = [png, pdf, gif]
        files = await collect_desc_images(ctx, png)
        self.assertEqual(files, ["file-1", "file-3"])
        png.to_file.assert_awaited_once()
