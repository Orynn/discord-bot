import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import data.db as db_module
from combat.commands import _send_board, edit_combat_board_message
from combat.discord_sync import (
    BoardEditResult,
    bind_bot,
    bind_pusher,
    clip_discord_content,
    discord_edit_lock,
    flush_discord_sync,
    forget_stale_ended,
    sync_combat_message,
    take_stale_ended,
)
from combat.storage import (
    CombatState,
    CombatantState,
    clear_combat,
    get_combat,
    save_combat,
)
from combat.text import discord_board_unavailable
from data.db import init_db


def _hero_state(*, board_message_id: int | None = 11) -> CombatState:
    return CombatState(
        guild_id=1,
        channel_id=4,
        scope_id=5,
        board_message_id=board_message_id,
        turn_order=["Hero"],
        active_index=0,
        combatants={
            "hero": CombatantState(
                name="Hero",
                user_id=1,
                hp=8,
                max_hp=8,
                hand=[],
                deck=[],
                x=1,
                y=1,
            )
        },
    )


def _http_error(status: int, reason: str) -> discord.HTTPException:
    response = MagicMock()
    response.status = status
    response.reason = reason
    return discord.HTTPException(response, {"message": reason})


def _mock_channel_with_message() -> tuple[MagicMock, MagicMock]:
    message = MagicMock()
    message.edit = AsyncMock()
    channel = MagicMock()
    channel.get_partial_message = MagicMock(return_value=message)
    return channel, message


class TestClipDiscordContent(unittest.TestCase):
    def test_clips_over_limit(self) -> None:
        text = "a" * 2500
        clipped = clip_discord_content(text)
        assert clipped is not None
        self.assertEqual(len(clipped), 2000)
        self.assertTrue(clipped.endswith("…"))
        self.assertEqual(clip_discord_content("ok"), "ok")
        self.assertIsNone(clip_discord_content(None))


class TestSyncCombatMessage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        init_db()

    async def asyncTearDown(self) -> None:
        await flush_discord_sync()
        forget_stale_ended(guild_id=1, scope_id=5)
        bind_bot(None)
        bind_pusher(None)
        db_module.DB_FILE = self._original
        self._tmpdir.cleanup()

    async def test_noops_without_pusher_or_message(self) -> None:
        called: list[bool] = []

        async def fake_push(state, *, content, ended):
            called.append(True)
            return BoardEditResult.UPDATED

        sync_combat_message(_hero_state(), content="move", ended=False)
        await flush_discord_sync()
        self.assertEqual(called, [])
        bind_pusher(fake_push)
        sync_combat_message(
            _hero_state(board_message_id=None), content="move", ended=False
        )
        await flush_discord_sync()
        self.assertEqual(called, [])
        save_combat(_hero_state())
        sync_combat_message(_hero_state(), content="Hero avance.", ended=False)
        await flush_discord_sync()
        self.assertEqual(called, [True])

    async def test_coalesces_edits_to_latest(self) -> None:
        save_combat(_hero_state())
        started = asyncio.Event()
        release = asyncio.Event()
        contents: list[str | None] = []

        async def fake_push(state, *, content, ended):
            contents.append(content)
            if not started.is_set():
                started.set()
                await release.wait()
            return BoardEditResult.UPDATED

        bind_pusher(fake_push)
        sync_combat_message(_hero_state(), content="one", ended=False)
        await started.wait()
        sync_combat_message(_hero_state(), content="two", ended=False)
        sync_combat_message(_hero_state(), content="three", ended=False)
        release.set()
        await flush_discord_sync()
        self.assertEqual(contents, ["one", "three"])

    async def test_ended_edit_runs_after_live_combat_is_cleared(self) -> None:
        save_combat(_hero_state())
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[bool, str | None]] = []

        async def fake_push(state, *, content, ended):
            calls.append((ended, content))
            if not started.is_set():
                started.set()
                await release.wait()
            return BoardEditResult.UPDATED

        bind_pusher(fake_push)
        sync_combat_message(_hero_state(), content="live", ended=False)
        await started.wait()
        clear_combat(guild_id=1, scope_id=5)
        ended_state = _hero_state()
        ended_state.log = ["Victoire"]
        sync_combat_message(ended_state, content="terminé", ended=True)
        release.set()
        await flush_discord_sync()
        self.assertEqual(calls, [(False, "live"), (True, "terminé")])

    async def test_send_board_waits_for_in_flight_web_edit(self) -> None:
        save_combat(_hero_state())
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def fake_push(state, *, content, ended):
            order.append("web")
            started.set()
            await release.wait()
            order.append("web-done")
            return BoardEditResult.UPDATED

        bind_pusher(fake_push)
        channel, message = _mock_channel_with_message()

        async def tracked_edit(**kwargs):
            order.append("board")

        message.edit = AsyncMock(side_effect=tracked_edit)
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        ctx = MagicMock()

        sync_combat_message(_hero_state(), content="web", ended=False)
        await started.wait()
        self.assertTrue(discord_edit_lock(guild_id=1, scope_id=5).locked())
        send_task = asyncio.create_task(
            _send_board(ctx, _hero_state(), content="Maj")
        )
        for _ in range(20):
            if send_task.done():
                break
            await asyncio.sleep(0)
        self.assertFalse(send_task.done())
        self.assertNotIn("board", order)
        release.set()
        await send_task
        await flush_discord_sync()
        self.assertEqual(order, ["web", "web-done", "board"])

    async def test_failed_ended_edit_can_be_retried(self) -> None:
        async def fake_push(state, *, content, ended):
            return BoardEditResult.FAILED

        bind_pusher(fake_push)
        sync_combat_message(_hero_state(), content="terminé", ended=True)
        await flush_discord_sync()
        stale = take_stale_ended(guild_id=1, scope_id=5)
        self.assertIsNotNone(stale)
        assert stale is not None
        snapshot, note = stale

        channel, message = _mock_channel_with_message()
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        ctx = MagicMock()
        with patch("combat.commands.send_message", AsyncMock()) as send:
            await _send_board(ctx, snapshot, content=note, combat_over=True)
        send.assert_not_called()
        message.edit.assert_awaited_once()
        kwargs = message.edit.await_args.kwargs
        self.assertEqual(kwargs["content"], "terminé")
        self.assertIsNone(kwargs["view"])
        self.assertIsNone(take_stale_ended(guild_id=1, scope_id=5))

    async def test_edit_combat_board_message_updates_discord(self) -> None:
        channel, message = _mock_channel_with_message()
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)

        result = await edit_combat_board_message(
            _hero_state(), content="Hero avance.", ended=False
        )
        self.assertEqual(result, BoardEditResult.UPDATED)
        message.edit.assert_awaited_once()
        kwargs = message.edit.await_args.kwargs
        self.assertEqual(kwargs["content"], "Hero avance.")
        self.assertIsInstance(kwargs["embed"], discord.Embed)
        self.assertIn("attachments", kwargs)
        self.assertNotIn("view", kwargs)
        channel.fetch_message.assert_not_called()

    async def test_edit_omits_overlong_overflow_and_clears_view_when_ended(
        self,
    ) -> None:
        channel, message = _mock_channel_with_message()
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)

        result = await edit_combat_board_message(
            _hero_state(), content="x" * 2500, ended=True
        )
        self.assertEqual(result, BoardEditResult.UPDATED)
        kwargs = message.edit.await_args.kwargs
        self.assertEqual(len(kwargs["content"]), 2000)
        self.assertIsNone(kwargs["view"])

    async def test_edit_combat_board_message_not_found_persists(self) -> None:
        channel, message = _mock_channel_with_message()
        message.edit = AsyncMock(
            side_effect=discord.NotFound(
                _http_error(404, "Not Found").response,
                {"message": "Unknown Message"},
            )
        )
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        state = _hero_state()
        save_combat(state)

        result = await edit_combat_board_message(state, content="Hero avance.")
        self.assertEqual(result, BoardEditResult.MISSING)
        self.assertIsNone(state.board_message_id)
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertIsNone(loaded.board_message_id)

    async def test_not_found_does_not_clobber_newer_combat_state(self) -> None:
        save_combat(_hero_state())
        current = get_combat(guild_id=1, scope_id=5)
        assert current is not None
        current.combatants["hero"].hp = 3
        current.log = ["Attaque"]
        save_combat(current)

        channel, message = _mock_channel_with_message()
        message.edit = AsyncMock(
            side_effect=discord.NotFound(
                _http_error(404, "Not Found").response,
                {"message": "Unknown Message"},
            )
        )
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)

        stale = _hero_state()
        result = await edit_combat_board_message(stale, content="Hero avance.")
        self.assertEqual(result, BoardEditResult.MISSING)
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.combatants["hero"].hp, 3)
        self.assertEqual(loaded.log, ["Attaque"])
        self.assertIsNone(loaded.board_message_id)

    async def test_edit_rate_limit_does_not_clear_id(self) -> None:
        channel, message = _mock_channel_with_message()
        message.edit = AsyncMock(side_effect=_http_error(429, "Too Many Requests"))
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        state = _hero_state()
        save_combat(state)

        result = await edit_combat_board_message(state, content="Hero avance.")
        self.assertEqual(result, BoardEditResult.FAILED)
        self.assertEqual(state.board_message_id, 11)
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 11)

    async def test_send_board_records_message_id(self) -> None:
        state = _hero_state(board_message_id=None)
        save_combat(state)
        posted = MagicMock()
        posted.id = 555
        posted.channel.id = 4
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock(return_value=posted)
        ) as send:
            await _send_board(ctx, state)
        send.assert_awaited_once()
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 555)

    async def test_send_board_records_id_without_clobbering_hp(self) -> None:
        state = _hero_state(board_message_id=None)
        save_combat(state)
        current = get_combat(guild_id=1, scope_id=5)
        assert current is not None
        current.combatants["hero"].hp = 3
        save_combat(current)
        posted = MagicMock()
        posted.id = 555
        posted.channel.id = 4
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock(return_value=posted)
        ):
            await _send_board(ctx, state)
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 555)
        self.assertEqual(loaded.combatants["hero"].hp, 3)

    async def test_send_board_clips_content_on_new_post(self) -> None:
        state = _hero_state(board_message_id=None)
        save_combat(state)
        posted = MagicMock()
        posted.id = 555
        posted.channel.id = 4
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock(return_value=posted)
        ) as send:
            await _send_board(ctx, state, content="x" * 2500)
        send.assert_awaited_once()
        self.assertEqual(len(send.await_args.kwargs["content"]), 2000)

    async def test_send_board_edits_in_place(self) -> None:
        state = _hero_state()
        save_combat(state)
        channel, message = _mock_channel_with_message()
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock()
        ) as send:
            await _send_board(ctx, state, content="Maj")
        send.assert_not_called()
        message.edit.assert_awaited_once()
        self.assertIn("view", message.edit.await_args.kwargs)

    async def test_send_board_does_not_repost_on_rate_limit(self) -> None:
        state = _hero_state()
        save_combat(state)
        channel, message = _mock_channel_with_message()
        message.edit = AsyncMock(side_effect=_http_error(429, "Too Many Requests"))
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock()
        ) as send, patch(
            "combat.commands.command_reply", AsyncMock()
        ) as reply:
            await _send_board(ctx, state)
        send.assert_not_called()
        reply.assert_awaited_once()
        self.assertEqual(reply.await_args.args[1], discord_board_unavailable())
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 11)

    async def test_send_board_reposts_when_message_missing(self) -> None:
        state = _hero_state()
        save_combat(state)
        channel, message = _mock_channel_with_message()
        message.edit = AsyncMock(
            side_effect=discord.NotFound(
                _http_error(404, "Not Found").response, {"message": "Unknown"}
            )
        )
        bot = MagicMock()
        bot.get_channel.return_value = channel
        bind_bot(bot)
        posted = MagicMock()
        posted.id = 777
        posted.channel.id = 4
        ctx = MagicMock()
        with patch(
            "combat.commands.send_message", AsyncMock(return_value=posted)
        ) as send:
            await _send_board(ctx, state)
        send.assert_awaited_once()
        loaded = get_combat(guild_id=1, scope_id=5)
        assert loaded is not None
        self.assertEqual(loaded.board_message_id, 777)
