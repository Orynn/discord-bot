import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from campaign.importing import (
    _fill_thread,
    has_import_placeholder,
    has_wiki_continuation,
    import_wiki_cluster,
    repair_placeholder_posts,
)
from campaign.wiki import WikiError, WikiPage


def _history(messages: list):
    def history(*, limit: int = 10, oldest_first: bool = True):
        del limit, oldest_first

        async def generate():
            for message in messages:
                yield message

        return generate()

    return history


def _page(title: str) -> WikiPage:
    return WikiPage(
        title=title,
        url=f"https://wiki.example/{title}",
        summary=f"{title} est une cité.",
        body="",
        section="lieux",
    )


class TestImportPlaceholder(unittest.TestCase):
    def test_detects_placeholder(self) -> None:
        self.assertTrue(has_import_placeholder("**Padhiver**\n_Import des liens…_"))
        self.assertFalse(has_import_placeholder("**Padhiver** est une cité."))
        self.assertFalse(has_import_placeholder(None))

    def test_detects_wiki_continuation(self) -> None:
        self.assertTrue(
            has_wiki_continuation("suite du lore\n\n_… suite sur le wiki._")
        )
        self.assertFalse(has_wiki_continuation("**Padhiver** est une cité."))
        self.assertFalse(has_wiki_continuation(None))


class TestFillThread(unittest.IsolatedAsyncioTestCase):
    async def test_edits_starter_instead_of_sending_a_new_message(self) -> None:
        starter = SimpleNamespace(
            id=1, content="**Padhiver**\n_Import des liens…_", edit=AsyncMock()
        )
        thread = SimpleNamespace(
            archived=False,
            send=AsyncMock(),
            history=_history([starter]),
        )
        await _fill_thread(thread, starter, ["**Padhiver** est une cité.", "suite"])
        starter.edit.assert_awaited_with(content="**Padhiver** est une cité.")
        thread.send.assert_awaited_once_with("suite")

    async def test_edits_existing_followups_instead_of_duplicating(self) -> None:
        starter = SimpleNamespace(id=1, content="ancien starter", edit=AsyncMock())
        followup = SimpleNamespace(id=2, content="ancien followup", edit=AsyncMock())
        thread = SimpleNamespace(
            archived=False,
            send=AsyncMock(),
            history=_history([starter, followup]),
        )
        await _fill_thread(thread, starter, ["nouveau starter", "nouveau followup"])
        starter.edit.assert_awaited_with(content="nouveau starter")
        followup.edit.assert_awaited_with(content="nouveau followup")
        thread.send.assert_not_called()

    async def test_skips_human_followups_and_does_not_append_after_them(self) -> None:
        bot = SimpleNamespace(id=1, bot=True)
        human = SimpleNamespace(id=42, bot=False)
        starter = SimpleNamespace(
            id=1, content="_Import des liens…_", edit=AsyncMock(), author=bot
        )
        player = SimpleNamespace(
            id=2,
            content="commentaire joueur",
            edit=AsyncMock(),
            author=human,
            attachments=[],
        )
        thread = SimpleNamespace(
            archived=False,
            send=AsyncMock(),
            history=_history([starter, player]),
            guild=SimpleNamespace(me=bot),
        )
        await _fill_thread(thread, starter, ["nouveau starter", "suite wiki"])
        starter.edit.assert_awaited_with(content="nouveau starter")
        player.edit.assert_not_called()
        thread.send.assert_not_called()

    async def test_resolves_missing_starter_message(self) -> None:
        starter = SimpleNamespace(
            id=10, content="_Import des liens…_", edit=AsyncMock()
        )
        thread = SimpleNamespace(
            id=10,
            starter_message=None,
            archived=False,
            send=AsyncMock(),
            fetch_message=AsyncMock(return_value=starter),
            history=_history([starter]),
        )
        await _fill_thread(thread, None, ["contenu réel"])
        starter.edit.assert_awaited_with(content="contenu réel")
        thread.send.assert_not_called()


class TestRepairPlaceholderPosts(unittest.IsolatedAsyncioTestCase):
    async def test_fills_threads_stuck_on_placeholder(self) -> None:
        starter = SimpleNamespace(
            id=10, content="**Padhiver**\n_Import des liens…_", edit=AsyncMock()
        )
        thread = SimpleNamespace(
            id=10,
            name="Padhiver",
            archived=False,
            locked=False,
            jump_url="https://discord.com/channels/1/10",
            starter_message=starter,
            send=AsyncMock(),
            fetch_message=AsyncMock(return_value=starter),
            history=_history([starter]),
        )
        forum = SimpleNamespace(id=1, name="📍 lieux", threads=[thread])

        async def archived_threads(*, limit: int = 100, before=None):
            del limit, before
            if False:
                yield None

        forum.archived_threads = archived_threads

        with (
            patch(
                "campaign.importing.ensure_default_campaign_forums",
                new_callable=AsyncMock,
            ),
            patch("campaign.importing.list_campaign_forums", return_value=[forum]),
            patch(
                "campaign.importing.fetch_wiki_page",
                new=AsyncMock(return_value=_page("Padhiver")),
            ),
            patch("campaign.importing.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await repair_placeholder_posts(SimpleNamespace(id=1))  # type: ignore[arg-type]

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.repaired, [thread])
        self.assertEqual(result.missing_wiki, ())
        starter.edit.assert_awaited()
        self.assertNotIn("Import des liens", starter.edit.await_args.kwargs["content"])

    async def test_fills_threads_truncated_with_wiki_continuation(self) -> None:
        bot = SimpleNamespace(id=99, bot=True)
        starter = SimpleNamespace(
            id=10,
            content="**Padhiver** est une cité.",
            edit=AsyncMock(),
            author=bot,
        )
        followup = SimpleNamespace(
            id=11,
            content="Début du lore.\n\n_… suite sur le wiki._",
            edit=AsyncMock(),
            author=bot,
            attachments=[],
        )
        thread = SimpleNamespace(
            id=10,
            name="Padhiver",
            archived=False,
            locked=False,
            jump_url="https://discord.com/channels/1/10",
            starter_message=starter,
            send=AsyncMock(),
            fetch_message=AsyncMock(return_value=starter),
            history=_history([starter, followup]),
            guild=SimpleNamespace(me=bot),
        )
        forum = SimpleNamespace(id=1, name="📍 lieux", threads=[thread])

        async def archived_threads(*, limit: int = 100, before=None):
            del limit, before
            if False:
                yield None

        forum.archived_threads = archived_threads
        long_page = WikiPage(
            title="Padhiver",
            url="https://wiki.example/Padhiver",
            summary="**Padhiver** est une cité.",
            body="\n\n".join(
                f"Paragraphe {index} de lore détaillé." for index in range(40)
            ),
            section="lieux",
        )

        with (
            patch(
                "campaign.importing.ensure_default_campaign_forums",
                new_callable=AsyncMock,
            ),
            patch("campaign.importing.list_campaign_forums", return_value=[forum]),
            patch(
                "campaign.importing.fetch_wiki_page",
                new=AsyncMock(return_value=long_page),
            ),
            patch("campaign.importing.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await repair_placeholder_posts(SimpleNamespace(id=1))  # type: ignore[arg-type]

        self.assertEqual(result.scanned, 1)
        self.assertEqual(result.repaired, [thread])
        filled: list[str] = []
        if starter.edit.await_args is not None:
            filled.append(starter.edit.await_args.kwargs["content"])
        if followup.edit.await_args is not None:
            filled.append(followup.edit.await_args.kwargs["content"])
        filled.extend(call.args[0] for call in thread.send.await_args_list)
        joined = "\n".join(filled)
        self.assertTrue(filled)
        self.assertNotIn("suite sur le wiki", joined.casefold())
        self.assertIn("Paragraphe", joined)


class TestImportWikiCluster(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        from campaign.importing import _guild_locks

        _guild_locks.clear()

    async def test_creates_thread_with_real_content_not_placeholder(self) -> None:
        starter = SimpleNamespace(id=1, content="", edit=AsyncMock())
        thread = SimpleNamespace(
            id=1,
            name="Padhiver",
            jump_url="https://discord.com/channels/1/2/3",
            archived=False,
            send=AsyncMock(),
            history=_history([starter]),
        )
        forum = SimpleNamespace(
            id=10,
            name="📍 lieux",
            threads=[],
            create_thread=AsyncMock(
                return_value=SimpleNamespace(thread=thread, message=starter)
            ),
        )
        page = WikiPage(
            title="Padhiver",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Padhiver",
            summary="**Padhiver**\n**Type:** cité",
            body="Une cité raffinée.",
            section="lieux",
        )

        with (
            patch(
                "campaign.importing.ensure_default_campaign_forums",
                new_callable=AsyncMock,
            ),
            patch(
                "campaign.importing.ensure_campaign_forum",
                new_callable=AsyncMock,
                return_value=forum,
            ),
            patch("campaign.importing.list_campaign_forums", return_value=[forum]),
            patch(
                "campaign.importing.locate_campaign_thread",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "campaign.importing.download_thumbnail",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("campaign.importing.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await import_wiki_cluster(guild=SimpleNamespace(id=7), root=page)  # type: ignore[arg-type]

        self.assertEqual(len(result.posts), 1)
        self.assertTrue(result.posts[0].created)
        content = forum.create_thread.await_args.kwargs["content"]
        self.assertNotIn("Import des liens", content)
        self.assertIn("Padhiver", content)
        self.assertIn("cité", content)
        starter.edit.assert_awaited()

    async def test_rejects_overlapping_imports(self) -> None:
        from campaign.importing import _lock_for

        lock = _lock_for(7)
        await lock.acquire()
        try:
            with self.assertRaises(WikiError):
                await import_wiki_cluster(
                    guild=SimpleNamespace(id=7),  # type: ignore[arg-type]
                    root=_page("Padhiver"),
                )
        finally:
            lock.release()

    async def test_follow_links_creates_infobox_posts_and_rewrites_jumps(self) -> None:
        padhiver = WikiPage(
            title="Padhiver",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Padhiver",
            summary=(
                "**Padhiver**\n**Religion:** "
                "[Tymora](<https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora>)"
            ),
            body="",
            section="lieux",
            outgoing=("Tymora",),
            infobox_outgoing=("Tymora",),
        )
        tymora = WikiPage(
            title="Tymora",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora",
            summary="**Tymora**",
            body="",
            section="pantheon",
        )
        created: dict[str, SimpleNamespace] = {}

        def _create_thread(**kwargs):
            title = kwargs["name"]
            thread_id = 10 + len(created)
            starter = SimpleNamespace(
                id=thread_id, content=kwargs["content"], edit=AsyncMock()
            )
            thread = SimpleNamespace(
                id=thread_id,
                name=title,
                jump_url=f"https://discord.com/channels/1/{thread_id}",
                archived=False,
                send=AsyncMock(),
                history=_history([starter]),
            )
            created[title] = SimpleNamespace(starter=starter, jump_url=thread.jump_url)
            return SimpleNamespace(thread=thread, message=starter)

        lieux = SimpleNamespace(
            id=1,
            name="📍 lieux",
            threads=[],
            create_thread=AsyncMock(side_effect=_create_thread),
        )
        pantheon = SimpleNamespace(
            id=2,
            name="📜 pantheon",
            threads=[],
            create_thread=AsyncMock(side_effect=_create_thread),
        )

        async def ensure_forum(_guild, section: str):
            return lieux if section == "lieux" else pantheon

        with (
            patch(
                "campaign.importing.ensure_default_campaign_forums",
                new_callable=AsyncMock,
            ),
            patch("campaign.importing.ensure_campaign_forum", side_effect=ensure_forum),
            patch(
                "campaign.importing.list_campaign_forums",
                return_value=[lieux, pantheon],
            ),
            patch(
                "campaign.importing.locate_campaign_thread",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "campaign.importing.download_thumbnail",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("campaign.wiki.fetch_wiki_page", new=AsyncMock(return_value=tymora)),
            patch("campaign.importing.asyncio.sleep", new_callable=AsyncMock),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await import_wiki_cluster(
                guild=SimpleNamespace(id=7),  # type: ignore[arg-type]
                root=padhiver,
                follow_links=True,
            )

        self.assertEqual(
            {post.page.title for post in result.posts}, {"Padhiver", "Tymora"}
        )
        edited = created["Padhiver"].starter.edit.await_args.kwargs["content"]
        self.assertIn(created["Tymora"].jump_url, edited)
        self.assertNotIn(
            "le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora", edited
        )

    async def test_follow_links_rewrites_existing_root(self) -> None:
        padhiver = WikiPage(
            title="Padhiver",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Padhiver",
            summary=(
                "**Padhiver**\n**Religion:** "
                "[Tymora](<https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora>)"
            ),
            body="",
            section="lieux",
            outgoing=("Tymora",),
            infobox_outgoing=("Tymora",),
        )
        tymora = WikiPage(
            title="Tymora",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora",
            summary="**Tymora**",
            body="",
            section="pantheon",
        )
        root_starter = SimpleNamespace(
            id=1, content="**Padhiver** déjà importé", edit=AsyncMock()
        )
        root_thread = SimpleNamespace(
            id=1,
            name="Padhiver",
            jump_url="https://discord.com/channels/1/1",
            archived=False,
            send=AsyncMock(),
            history=_history([root_starter]),
            starter_message=root_starter,
            fetch_message=AsyncMock(return_value=root_starter),
            guild=SimpleNamespace(me=SimpleNamespace(id=99, bot=True)),
        )
        tymora_starter = SimpleNamespace(id=2, content="", edit=AsyncMock())
        tymora_thread = SimpleNamespace(
            id=2,
            name="Tymora",
            jump_url="https://discord.com/channels/1/2",
            archived=False,
            send=AsyncMock(),
            history=_history([tymora_starter]),
        )

        async def locate(_forums, title: str):
            return root_thread if title == "Padhiver" else None

        pantheon = SimpleNamespace(
            id=11,
            name="📜 pantheon",
            threads=[],
            create_thread=AsyncMock(
                return_value=SimpleNamespace(
                    thread=tymora_thread, message=tymora_starter
                )
            ),
        )
        lieux = SimpleNamespace(id=10, name="📍 lieux", threads=[root_thread])

        async def ensure_forum(_guild, section: str):
            return lieux if section == "lieux" else pantheon

        with (
            patch(
                "campaign.importing.ensure_default_campaign_forums",
                new_callable=AsyncMock,
            ),
            patch("campaign.importing.ensure_campaign_forum", side_effect=ensure_forum),
            patch(
                "campaign.importing.list_campaign_forums",
                return_value=[lieux, pantheon],
            ),
            patch("campaign.importing.locate_campaign_thread", side_effect=locate),
            patch(
                "campaign.importing.download_thumbnail",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("campaign.wiki.fetch_wiki_page", new=AsyncMock(return_value=tymora)),
            patch("campaign.importing.asyncio.sleep", new_callable=AsyncMock),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await import_wiki_cluster(
                guild=SimpleNamespace(id=7),  # type: ignore[arg-type]
                root=padhiver,
                follow_links=True,
            )

        self.assertFalse(result.posts[0].created)
        self.assertTrue(
            any(post.created and post.page.title == "Tymora" for post in result.posts)
        )
        root_starter.edit.assert_awaited()
        edited = root_starter.edit.await_args.kwargs["content"]
        self.assertIn("https://discord.com/channels/1/2", edited)
        self.assertNotIn(
            "le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Tymora", edited
        )
