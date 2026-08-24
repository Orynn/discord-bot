import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from campaign.forums import CampaignForumError
from campaign.moving import (
    is_move_note,
    move_campaign_post,
    rewrite_moved_links,
)


def _history(messages: list):
    def history(*, limit: int = 50, oldest_first: bool = True):
        del limit, oldest_first

        async def generate():
            for message in messages:
                yield message

        return generate()

    return history


def _message(content: str, *, message_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id, content=content, attachments=[], edit=AsyncMock()
    )


def _thread(
    thread_id: int,
    name: str,
    *,
    parent_id: int,
    messages: list | None = None,
    archived: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=thread_id,
        name=name,
        parent_id=parent_id,
        archived=archived,
        locked=False,
        jump_url=f"https://discord.com/channels/1/{thread_id}",
        mention=f"<#{thread_id}>",
        send=AsyncMock(),
        edit=AsyncMock(),
        history=_history(messages or []),
    )


def _forum(forum_id: int, name: str, threads: list) -> SimpleNamespace:
    forum = SimpleNamespace(
        id=forum_id,
        name=name,
        threads=threads,
        mention=f"<#{forum_id}>",
        create_thread=AsyncMock(),
    )

    async def archived_threads(*, limit: int = 100, before=None):
        del limit, before
        if False:
            yield None

    forum.archived_threads = archived_threads
    return forum


class TestRewriteMovedLinks(unittest.TestCase):
    def test_replaces_jump_url_and_connection_section(self) -> None:
        text = (
            "**Liens**\n"
            "• 📍 lieux — [Padhiver](https://discord.com/channels/1/10)\n"
            "• 👤 pnj — [Elminster](https://discord.com/channels/1/20)"
        )
        updated = rewrite_moved_links(
            text,
            old_thread_id=10,
            new_url="https://discord.com/channels/1/99",
            title="Padhiver",
            old_section="📍 lieux",
            new_section="🧝 race",
        )
        self.assertIn(
            "🧝 race — [Padhiver](https://discord.com/channels/1/99)", updated
        )
        self.assertIn(
            "👤 pnj — [Elminster](https://discord.com/channels/1/20)", updated
        )
        self.assertNotIn("https://discord.com/channels/1/10", updated)

    def test_replaces_jump_url_with_message_id(self) -> None:
        text = "[Padhiver](https://discord.com/channels/1/10/555)"
        updated = rewrite_moved_links(
            text,
            old_thread_id=10,
            new_url="https://discord.com/channels/1/99",
            title="Padhiver",
            old_section="📍 lieux",
            new_section="🧝 race",
        )
        self.assertEqual(updated, "[Padhiver](https://discord.com/channels/1/99)")

    def test_move_notes(self) -> None:
        self.assertTrue(
            is_move_note("_Déplacé vers https://discord.com/channels/1/2 (pnj)._")
        )
        self.assertTrue(
            is_move_note("_Recatégorisé vers https://example.com (lieux)._")
        )
        self.assertFalse(is_move_note("**Padhiver** est une cité."))


class TestMoveCampaignPost(unittest.IsolatedAsyncioTestCase):
    async def test_copies_post_and_rewrites_connections(self) -> None:
        starter = _message("**Padhiver** est une cité.")
        source = _thread(10, "Padhiver", parent_id=1, messages=[starter])
        linked_message = _message(
            "• 📍 lieux — [Padhiver](https://discord.com/channels/1/10)"
        )
        linked = _thread(20, "Elminster", parent_id=2, messages=[linked_message])
        created = _thread(99, "Padhiver", parent_id=3, messages=[])
        lieux = _forum(1, "📍 lieux", [source])
        pnj = _forum(2, "👤 pnj", [linked])
        race = _forum(3, "🧝 race", [])
        race.create_thread = AsyncMock(
            return_value=SimpleNamespace(thread=created, message=None)
        )

        with (
            patch(
                "campaign.moving.list_campaign_forums", return_value=[lieux, pnj, race]
            ),
            patch("campaign.moving.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await move_campaign_post(
                guild=SimpleNamespace(),  # type: ignore[arg-type]
                thread=source,  # type: ignore[arg-type]
                target=race,  # type: ignore[arg-type]
            )

        self.assertTrue(result.created)
        self.assertEqual(result.thread.id, 99)
        self.assertEqual(result.relinked, 1)
        race.create_thread.assert_awaited()
        linked_message.edit.assert_awaited_with(
            content="• 🧝 race — [Padhiver](https://discord.com/channels/1/99)"
        )
        source.send.assert_awaited()
        source.edit.assert_awaited()

    async def test_skips_command_and_status_messages(self) -> None:
        wiki = _message("**Padhiver** est une cité.", message_id=1)
        command = _message(";campaign move race", message_id=2)
        status = _message("📦 Déplacement de **Padhiver** vers race…", message_id=3)
        source = _thread(10, "Padhiver", parent_id=1, messages=[wiki, command, status])
        created = _thread(99, "Padhiver", parent_id=3, messages=[])
        lieux = _forum(1, "📍 lieux", [source])
        race = _forum(3, "🧝 race", [])
        race.create_thread = AsyncMock(
            return_value=SimpleNamespace(thread=created, message=None)
        )

        with (
            patch("campaign.moving.list_campaign_forums", return_value=[lieux, race]),
            patch("campaign.moving.asyncio.sleep", new_callable=AsyncMock),
        ):
            await move_campaign_post(
                guild=SimpleNamespace(),  # type: ignore[arg-type]
                thread=source,  # type: ignore[arg-type]
                target=race,  # type: ignore[arg-type]
                skip_message_ids={2, 3},
            )

        kwargs = race.create_thread.await_args.kwargs
        self.assertEqual(kwargs["content"], "**Padhiver** est une cité.")
        created.send.assert_not_called()

    async def test_uses_existing_target_thread_and_relinks(self) -> None:
        source = _thread(10, "Padhiver", parent_id=1, messages=[_message("fiche")])
        existing = _thread(30, "Padhiver", parent_id=3, messages=[])
        linked_message = _message("[Padhiver](https://discord.com/channels/1/10)")
        linked = _thread(20, "Tymora", parent_id=2, messages=[linked_message])
        lieux = _forum(1, "📍 lieux", [source])
        pantheon = _forum(2, "📜 pantheon", [linked])
        race = _forum(3, "🧝 race", [existing])

        with (
            patch(
                "campaign.moving.list_campaign_forums",
                return_value=[lieux, pantheon, race],
            ),
            patch("campaign.moving.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await move_campaign_post(
                guild=SimpleNamespace(),  # type: ignore[arg-type]
                thread=source,  # type: ignore[arg-type]
                target=race,  # type: ignore[arg-type]
            )

        self.assertFalse(result.created)
        self.assertEqual(result.thread.id, 30)
        race.create_thread.assert_not_called()
        linked_message.edit.assert_awaited_with(
            content="[Padhiver](https://discord.com/channels/1/30)"
        )

    async def test_rejects_move_into_same_forum(self) -> None:
        source = _thread(10, "Padhiver", parent_id=1, messages=[_message("fiche")])
        lieux = _forum(1, "📍 lieux", [source])
        with patch("campaign.moving.list_campaign_forums", return_value=[lieux]):
            with self.assertRaises(CampaignForumError):
                await move_campaign_post(
                    guild=SimpleNamespace(),  # type: ignore[arg-type]
                    thread=source,  # type: ignore[arg-type]
                    target=lieux,  # type: ignore[arg-type]
                )
