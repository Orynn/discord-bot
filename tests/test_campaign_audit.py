import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from campaign.audit import AuditItem, audit_campaign_posts, classify_placement, format_audit_report
from campaign.forums import iter_forum_threads
from campaign.wiki import WikiNotFoundError, WikiPage


def _page(title: str, section: str) -> WikiPage:
    return WikiPage(
        title=title,
        url=f"https://wiki.example/{title}",
        summary=f"{title} summary",
        body="",
        section=section,
    )


def _thread(
    thread_id: int,
    name: str,
    *,
    archived: bool = False,
    locked: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=thread_id,
        name=name,
        archived=archived,
        locked=locked,
        jump_url=f"https://discord.com/channels/1/2/{thread_id}",
        mention=f"<#{thread_id}>",
        send=AsyncMock(),
        edit=AsyncMock(),
    )


def _forum(name: str, threads: list, archived: list | None = None) -> SimpleNamespace:
    forum = SimpleNamespace(
        name=name,
        threads=threads,
        mention=f"#{name}",
        create_thread=AsyncMock(),
    )

    async def archived_threads(*, limit: int = 100, before=None):  # noqa: ARG001
        del limit, before
        for thread in archived or []:
            yield thread

    forum.archived_threads = archived_threads
    return forum


class TestClassifyPlacement(unittest.TestCase):
    def test_ok_when_sections_match(self) -> None:
        self.assertEqual(
            classify_placement(current_section="📍 lieux", expected_section="lieux"),
            "ok",
        )

    def test_misplaced_when_sections_differ(self) -> None:
        self.assertEqual(
            classify_placement(current_section="lieux", expected_section="pnj"),
            "misplaced",
        )

    def test_missing_wiki_when_no_expected_section(self) -> None:
        self.assertEqual(
            classify_placement(current_section="lieux", expected_section=None),
            "missing_wiki",
        )


class TestFormatAuditReport(unittest.TestCase):
    def test_lists_misplaced_and_missing(self) -> None:
        report = format_audit_report(
            [
                AuditItem(
                    title="Padhiver",
                    jump_url="https://discord.test/padhiver",
                    current_section="lieux",
                    expected_section="lieux",
                    status="ok",
                ),
                AuditItem(
                    title="Elminster",
                    jump_url="https://discord.test/elminster",
                    current_section="lieux",
                    expected_section="pnj",
                    status="misplaced",
                    moved=True,
                ),
                AuditItem(
                    title="Inconnu",
                    jump_url="https://discord.test/inconnu",
                    current_section="divers",
                    expected_section=None,
                    status="missing_wiki",
                ),
            ]
        )
        self.assertIn("posts: 3", report)
        self.assertIn("ok: 1", report)
        self.assertIn("misplaced: 1", report)
        self.assertIn("missing_wiki: 1", report)
        self.assertIn("moved: 1", report)
        self.assertIn("Elminster  [lieux → pnj] → déplacé", report)
        self.assertIn("Inconnu  [divers]", report)


class TestIterForumThreads(unittest.IsolatedAsyncioTestCase):
    async def test_merges_active_and_archived_threads(self) -> None:
        active = _thread(1, "Padhiver")
        archived = _thread(2, "Eauprofonde", archived=True)
        forum = _forum("📍 lieux", [active], archived=[archived])
        threads = await iter_forum_threads(forum)  # type: ignore[arg-type]
        names = {thread.name for thread in threads}
        self.assertEqual(names, {"Padhiver", "Eauprofonde"})


class TestAuditCampaignPosts(unittest.IsolatedAsyncioTestCase):
    async def test_classifies_ok_misplaced_and_missing(self) -> None:
        ok_thread = _thread(1, "Padhiver")
        wrong_thread = _thread(2, "Elminster")
        missing_thread = _thread(3, "Inconnu")
        leftover = _thread(4, "Ancien", archived=True, locked=True)
        lieux = _forum("📍 lieux", [ok_thread, wrong_thread, leftover])
        divers = _forum("📦 divers", [missing_thread])

        async def fake_fetch(title: str, *, suggest: bool = True) -> WikiPage:
            del suggest
            pages = {
                "Padhiver": _page("Padhiver", "lieux"),
                "Elminster": _page("Elminster", "pnj"),
            }
            if title not in pages:
                raise WikiNotFoundError(title)
            return pages[title]

        with (
            patch("campaign.audit.ensure_default_campaign_forums", new_callable=AsyncMock),
            patch("campaign.audit.list_campaign_forums", return_value=[lieux, divers]),
            patch("campaign.audit.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.audit.asyncio.sleep", new_callable=AsyncMock),
        ):
            items = await audit_campaign_posts(SimpleNamespace())  # type: ignore[arg-type]

        by_title = {item.title: item for item in items}
        self.assertEqual(set(by_title), {"Padhiver", "Elminster", "Inconnu"})
        self.assertEqual(by_title["Padhiver"].status, "ok")
        self.assertEqual(by_title["Elminster"].status, "misplaced")
        self.assertEqual(by_title["Elminster"].expected_section, "pnj")
        self.assertEqual(by_title["Inconnu"].status, "missing_wiki")
        self.assertFalse(any(item.moved for item in items))

    async def test_fix_recreates_misplaced_thread_in_expected_forum(self) -> None:
        old = _thread(10, "Elminster")
        lieux = _forum("📍 lieux", [old])
        created = _thread(99, "Elminster")
        pnj = _forum("👤 pnj", [])
        pnj.create_thread = AsyncMock(
            return_value=SimpleNamespace(thread=created, message=None)
        )

        with (
            patch("campaign.audit.ensure_default_campaign_forums", new_callable=AsyncMock),
            patch("campaign.audit.list_campaign_forums", return_value=[lieux, pnj]),
            patch(
                "campaign.audit.fetch_wiki_page",
                new=AsyncMock(return_value=_page("Elminster", "pnj")),
            ),
            patch("campaign.audit.ensure_campaign_forum", new=AsyncMock(return_value=pnj)),
            patch(
                "campaign.audit.move_campaign_post",
                new=AsyncMock(return_value=SimpleNamespace(thread=created)),
            ),
            patch("campaign.audit.asyncio.sleep", new_callable=AsyncMock),
        ):
            items = await audit_campaign_posts(SimpleNamespace(), fix=True)  # type: ignore[arg-type]

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0].moved)
        self.assertEqual(items[0].status, "misplaced")
        self.assertEqual(items[0].current_section, "lieux")
        self.assertEqual(items[0].jump_url, created.jump_url)

    async def test_fix_archives_duplicate_when_target_already_has_title(self) -> None:
        old = _thread(10, "Elminster")
        existing = _thread(20, "Elminster")
        lieux = _forum("📍 lieux", [old])
        pnj = _forum("👤 pnj", [existing])

        with (
            patch("campaign.audit.ensure_default_campaign_forums", new_callable=AsyncMock),
            patch("campaign.audit.list_campaign_forums", return_value=[lieux, pnj]),
            patch(
                "campaign.audit.fetch_wiki_page",
                new=AsyncMock(return_value=_page("Elminster", "pnj")),
            ),
            patch("campaign.audit.ensure_campaign_forum", new=AsyncMock(return_value=pnj)),
            patch(
                "campaign.audit.move_campaign_post",
                new=AsyncMock(return_value=SimpleNamespace(thread=existing)),
            ),
            patch("campaign.audit.asyncio.sleep", new_callable=AsyncMock),
        ):
            items = await audit_campaign_posts(SimpleNamespace(), fix=True)  # type: ignore[arg-type]

        self.assertTrue(items[0].moved)
        self.assertEqual(items[0].jump_url, existing.jump_url)
        pnj.create_thread.assert_not_called()
