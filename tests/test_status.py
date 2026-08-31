import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sheets.commands.status import _send_sheet_status
from sheets.context import target_plain
from sheets.data import CharacterSheet
from sheets.embeds import build_status_embed


class TestTargetPlain(unittest.TestCase):
    def test_omits_markdown(self) -> None:
        sheet = CharacterSheet(name="Anorak")
        self.assertEqual(target_plain(None, sheet), "Anorak")
        member = MagicMock()
        member.display_name = "Tim"
        self.assertEqual(target_plain(member, sheet), "Anorak (Tim)")
        self.assertNotIn("**", target_plain(member, sheet))


class TestSendSheetStatus(unittest.IsolatedAsyncioTestCase):
    async def test_deletes_command_when_no_sheet(self) -> None:
        ctx = MagicMock()
        with (
            patch(
                "sheets.commands.status.get_sheet_for_owner",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "sheets.commands.status.delete_command", new_callable=AsyncMock
            ) as delete,
        ):
            await _send_sheet_status(ctx, None)
        delete.assert_awaited_once_with(ctx)

    async def test_syncs_hunger_saves_and_shows_notices(self) -> None:
        sheet = CharacterSheet(name="Anorak", hp_current=10, hp_max=10)
        ctx = MagicMock()
        ctx.guild.id = 11
        clock = MagicMock()
        with (
            patch(
                "sheets.commands.status.get_sheet_for_owner",
                new_callable=AsyncMock,
                return_value=(42, sheet),
            ),
            patch("sheets.commands.status.get_clock", return_value=clock),
            patch(
                "sheets.commands.status.apply_clock_hunger",
                return_value=(["starvation → exhaustion 1"], True),
            ) as sync,
            patch("sheets.commands.status.save_owner_sheet") as save,
            patch(
                "sheets.commands.status.send_message", new_callable=AsyncMock
            ) as send,
            patch(
                "sheets.commands.status.delete_command", new_callable=AsyncMock
            ),
        ):
            await _send_sheet_status(ctx, None)
        sync.assert_called_once_with(sheet, clock)
        save.assert_called_once()
        embed = send.await_args.kwargs["embed"]
        self.assertEqual(embed.title, "📌 Status — Anorak")
        starvation = next(
            field for field in embed.fields if field.name == "⚠️ Starvation"
        )
        self.assertIn("exhaustion 1", starvation.value)

    async def test_skips_save_when_hunger_unchanged(self) -> None:
        sheet = CharacterSheet(name="Anorak", hp_current=10, hp_max=10)
        ctx = MagicMock()
        ctx.guild.id = 11
        with (
            patch(
                "sheets.commands.status.get_sheet_for_owner",
                new_callable=AsyncMock,
                return_value=(42, sheet),
            ),
            patch("sheets.commands.status.get_clock", return_value=MagicMock()),
            patch(
                "sheets.commands.status.apply_clock_hunger",
                return_value=([], False),
            ),
            patch("sheets.commands.status.save_owner_sheet") as save,
            patch(
                "sheets.commands.status.send_message", new_callable=AsyncMock
            ),
            patch(
                "sheets.commands.status.delete_command", new_callable=AsyncMock
            ),
        ):
            await _send_sheet_status(ctx, None)
        save.assert_not_called()


class TestStatusEmbedNotices(unittest.TestCase):
    def test_omits_starvation_field_without_notices(self) -> None:
        embed = build_status_embed(CharacterSheet(name="Hero", hp_max=10, hp_current=10))
        names = [field.name for field in embed.fields]
        self.assertNotIn("⚠️ Starvation", names)
