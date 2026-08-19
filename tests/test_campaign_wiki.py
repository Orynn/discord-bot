import unittest
from unittest.mock import AsyncMock, patch

from campaign.wiki import (
    WIKI_BASE,
    WikiError,
    WikiNotFoundError,
    WikiPage,
    _is_skipped_template,
    collect_infobox_titles,
    collect_related_titles,
    connections_block,
    fetch_wiki_cluster,
    fetch_wiki_page,
    guess_section,
    is_generic_wiki_title,
    markdown_wiki_link,
    page_title_from_query,
    rewrite_imported_links,
    split_import_query,
    wikitext_to_body,
    wiki_to_plain,
)

SAMPLE = """
{{Homonymie}}
{{Région_ou_Pays
| image = Padhiver.jpg
| name = Padhiver
| type = cité
| région = [[Côte des Épées septentrionale]]
| races = [[humain]], [[nain]]
| religion = [[Tymora]]
| dirigeant = [[Nasher Alagondar]]
| nom VO = Neverwinter
}}
'''Padhiver''' est une cité de la [[Côte des Épées septentrionale]].

== Géographie ==
Elle se dresse à l'ouest du [[Bois du Padhiver]].

== Références ==
Should be ignored.
[[Catégorie:Ville]]
"""

PERSON = """
{{DISPLAYTITLE:Elminster Aumar}}
{{Personnage
| alias = Le Sage de Valombre
| nom_VO = Elminster
| race = [[humain]]
| occupation = Sage
}}
'''Elminster Aumar''' était un [[magicien]].
"""


class TestCampaignWiki(unittest.TestCase):
    def test_page_title_from_url(self) -> None:
        self.assertEqual(
            page_title_from_query(
                "https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Padhiver"
            ),
            "Padhiver",
        )
        self.assertEqual(
            page_title_from_query(
                "https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Bois_du_Padhiver"
            ),
            "Bois du Padhiver",
        )
        self.assertEqual(
            page_title_from_query("https://forgottenrealms.fandom.com/wiki/Neverwinter"),
            "Neverwinter",
        )

    def test_split_import_query(self) -> None:
        section, page, follow = split_import_query("lieux Padhiver")
        self.assertEqual(section, "lieux")
        self.assertEqual(page, "Padhiver")
        self.assertFalse(follow)
        section, page, follow = split_import_query("Eauprofonde")
        self.assertIsNone(section)
        self.assertEqual(page, "Eauprofonde")
        self.assertFalse(follow)
        section, page, follow = split_import_query("Padhiver --liens")
        self.assertIsNone(section)
        self.assertEqual(page, "Padhiver")
        self.assertTrue(follow)
        section, page, follow = split_import_query("--liens lieux Padhiver")
        self.assertEqual(section, "lieux")
        self.assertEqual(page, "Padhiver")
        self.assertTrue(follow)
        with self.assertRaises(WikiError):
            split_import_query("--liens")

    def test_plain_links_and_bold(self) -> None:
        plain = wiki_to_plain("'''Padhiver''' est dans la [[Côte des Épées septentrionale]].")
        self.assertIn("**Padhiver** est dans", plain)
        self.assertIn(
            markdown_wiki_link(
                label="Côte des Épées septentrionale",
                title="Côte des Épées septentrionale",
            ),
            plain,
        )
        self.assertIn(WIKI_BASE, plain)

    def test_parses_french_location_infobox_and_skips_references(self) -> None:
        name, fields, body = wikitext_to_body(SAMPLE)
        self.assertEqual(name, "Région_ou_Pays")
        self.assertEqual(fields["type"], "cité")
        self.assertIn("Côte des Épées septentrionale", fields["région"])
        self.assertIn("le-monde-des-royaumes-oublies.fandom.com/fr/wiki/", fields["région"])
        self.assertIn("**Padhiver** est une cité", body)
        self.assertIn("**Géographie**", body)
        self.assertNotIn("Références", body)
        self.assertNotIn("Should be ignored", body)

    def test_collects_specific_connections_and_skips_generic_races(self) -> None:
        titles = collect_related_titles(SAMPLE)
        folded = [title.casefold() for title in titles]
        self.assertIn("tymora", folded)
        self.assertIn("nasher alagondar", folded)
        self.assertIn("côte des épées septentrionale", folded)
        self.assertIn("bois du padhiver", folded)
        self.assertNotIn("humain", folded)
        self.assertNotIn("nain", folded)
        infobox = [title.casefold() for title in collect_infobox_titles(SAMPLE)]
        self.assertIn("tymora", infobox)
        self.assertIn("nasher alagondar", infobox)
        self.assertNotIn("bois du padhiver", infobox)

    def test_skips_sourcebooks_and_interwiki(self) -> None:
        self.assertTrue(is_generic_wiki_title("DD3 - Royaumes Oubliés - Univers"))
        self.assertTrue(is_generic_wiki_title("humain"))
        self.assertFalse(is_generic_wiki_title("Padhiver"))
        self.assertFalse(is_generic_wiki_title("Rashémi (ethnie)"))

    def test_rewrites_wiki_links_to_discord_jumps(self) -> None:
        text = markdown_wiki_link(label="Tymora", title="Tymora")
        jump = "https://discord.com/channels/1/2/3"
        rewritten = rewrite_imported_links(text, {"Tymora": jump})
        self.assertIn(jump, rewritten)
        self.assertNotIn("le-monde-des-royaumes-oublies.fandom.com", rewritten)

    def test_connections_block_lists_imported_posts(self) -> None:
        block = connections_block(
            outgoing=("Tymora", "Humain"),
            jump_urls={"Tymora": "https://discord.com/channels/1/2/3"},
            sections={"tymora": "📜 pantheon"},
        )
        self.assertIn("**Liens**", block)
        self.assertIn("📜 pantheon — [Tymora](https://discord.com/channels/1/2/3)", block)
        self.assertNotIn("Humain", block)

    def test_guesses_section_from_french_infobox_and_categories(self) -> None:
        self.assertEqual(guess_section(infobox_name="Région_ou_Pays", categories=["Ville"]), "lieux")
        self.assertEqual(guess_section(infobox_name="Personnage", categories=[]), "pnj")
        self.assertEqual(guess_section(infobox_name="Créature", categories=[]), "créatures")
        self.assertEqual(guess_section(infobox_name="Objet", categories=[]), "objets")
        self.assertEqual(guess_section(infobox_name="Plante", categories=[]), "flore")
        self.assertEqual(
            guess_section(infobox_name=None, categories=["Nourriture et Boisson"]),
            "objets",
        )
        self.assertEqual(guess_section(infobox_name=None, categories=["Food and drink"]), "objets")
        self.assertEqual(guess_section(infobox_name=None, categories=["Plante"]), "flore")
        self.assertEqual(guess_section(infobox_name=None, categories=["Vegetation"]), "flore")
        self.assertEqual(guess_section(infobox_name="Divinité", categories=[]), "pantheon")
        self.assertEqual(guess_section(infobox_name="Location", categories=["Settlements"]), "lieux")
        self.assertEqual(
            guess_section(infobox_name=None, categories=["Catégorie:Organisation"]),
            "organisations",
        )
        self.assertEqual(guess_section(infobox_name=None, categories=["Année"]), "divers")
        self.assertEqual(guess_section(infobox_name="Ethnie", categories=[]), "race")
        self.assertEqual(guess_section(infobox_name=None, categories=["Catégorie:Race"]), "race")
        self.assertEqual(
            guess_section(
                infobox_name="Organisation_et_églises",
                categories=["Catégorie:Classe"],
                infobox_fields={"type": "Classe"},
            ),
            "classe",
        )
        self.assertEqual(
            guess_section(
                infobox_name="Organisation_et_églises",
                categories=["Catégorie:Classe", "Catégorie:Profession"],
            ),
            "classe",
        )
        self.assertEqual(
            guess_section(infobox_name="Organisation_et_églises", categories=["Catégorie:Guilde"]),
            "organisations",
        )
        self.assertEqual(guess_section(infobox_name=None, categories=["Catégorie:Monnaie"]), "objets")
        self.assertEqual(
            guess_section(infobox_name="Objet", categories=[], infobox_fields={"type": "Monnaie"}),
            "objets",
        )
        self.assertEqual(guess_section(infobox_name=None, categories=["Portrait"]), "divers")
        self.assertEqual(guess_section(infobox_name=None, categories=["Consort"]), "divers")
        self.assertEqual(guess_section(infobox_name=None, categories=["Port"]), "lieux")
        self.assertEqual(guess_section(infobox_name=None, categories=["Sort"]), "sorts")
        self.assertEqual(guess_section(infobox_name=None, categories=["Divinités"]), "pantheon")

    def test_skip_template_prefix_ignores_short_keys(self) -> None:
        self.assertTrue(_is_skipped_template("Homonymie"))
        self.assertTrue(_is_skipped_template("Année/Personnages"))
        self.assertTrue(_is_skipped_template("source_livre"))
        self.assertFalse(_is_skipped_template("For_the_record"))
        self.assertFalse(_is_skipped_template("Map_of_Faerun"))
        self.assertFalse(_is_skipped_template("Région_ou_Pays"))

    def test_person_sample_skips_displaytitle(self) -> None:
        name, fields, body = wikitext_to_body(PERSON)
        self.assertEqual(name, "Personnage")
        self.assertEqual(fields["occupation"], "Sage")
        self.assertIn("magicien", body.casefold())

    def test_discord_chunks_include_attribution(self) -> None:
        page = WikiPage(
            title="Padhiver",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Padhiver",
            summary="**Padhiver**\n**Type:** cité",
            body="Une cité raffinée.",
            section="lieux",
        )
        chunks = page.discord_chunks()
        self.assertTrue(chunks)
        self.assertIn("CC BY-SA", chunks[0])
        self.assertIn("le-monde-des-royaumes-oublies.fandom.com", chunks[0])
        self.assertIn("Royaumes Oubliés", chunks[0])

    def test_preview_embeds_respect_discord_limit(self) -> None:
        from campaign.commands import _EMBED_DESCRIPTION_LIMIT, _wiki_preview_embeds

        page = WikiPage(
            title="Huge Article",
            url="https://le-monde-des-royaumes-oublies.fandom.com/fr/wiki/Huge",
            summary="**Huge Article**\n" + ("**Type:** City\n" * 200),
            body="Paragraph.\n\n" + ("Long lore line.\n" * 800),
            section="lieux",
        )
        embeds = _wiki_preview_embeds(page)
        self.assertGreater(len(embeds), 1)
        for embed in embeds:
            self.assertLessEqual(len(embed.description or ""), _EMBED_DESCRIPTION_LIMIT)

    def test_preview_embed_mentions_suggestion_fallback(self) -> None:
        from campaign.commands import _wiki_preview_embeds

        page = WikiPage(
            title="Padhiver",
            url=f"{WIKI_BASE}Padhiver",
            summary="**Padhiver**",
            body="Cité.",
            section="lieux",
            suggested_from="Neverwinter",
        )
        embed = _wiki_preview_embeds(page)[0]
        field = next(field for field in embed.fields if field.name == "🔎 Suggestion")
        self.assertIn("Neverwinter", field.value)
        self.assertIn("Padhiver", field.value)


def _page(title: str, *outgoing: str, infobox: tuple[str, ...] | None = None) -> WikiPage:
    return WikiPage(
        title=title,
        url=f"{WIKI_BASE}{title.replace(' ', '_')}",
        summary=f"**{title}**",
        body="",
        section="lieux",
        outgoing=outgoing,
        infobox_outgoing=infobox if infobox is not None else outgoing,
    )


class TestWikiClusterCrawl(unittest.IsolatedAsyncioTestCase):
    async def test_bfs_follows_nested_connections(self) -> None:
        catalog = {
            "Padhiver": _page("Padhiver", "Tymora", "Luskan"),
            "Tymora": _page("Tymora", "Lathandre"),
            "Luskan": _page("Luskan"),
            "Lathandre": _page("Lathandre"),
        }

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            return catalog[query]

        with (
            patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            cluster = await fetch_wiki_cluster(catalog["Padhiver"], depth=8)

        titles = [page.title for page in cluster.pages]
        self.assertEqual(titles, ["Padhiver", "Tymora", "Luskan", "Lathandre"])
        self.assertEqual(cluster.aliases["Tymora"], "Tymora")
        self.assertFalse(cluster.truncated)

    async def test_default_depth_imports_root_only(self) -> None:
        catalog = {
            "Padhiver": _page("Padhiver", "Tymora", "Luskan"),
            "Tymora": _page("Tymora"),
        }

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            return catalog[query]

        with patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch):
            cluster = await fetch_wiki_cluster(catalog["Padhiver"])

        self.assertEqual([page.title for page in cluster.pages], ["Padhiver"])
        self.assertFalse(cluster.truncated)

    async def test_infobox_only_skips_body_links_and_does_not_recurse(self) -> None:
        catalog = {
            "Padhiver": _page(
                "Padhiver",
                "Tymora",
                "Bois du Padhiver",
                infobox=("Tymora",),
            ),
            "Tymora": _page("Tymora", "Lathandre"),
            "Bois du Padhiver": _page("Bois du Padhiver"),
            "Lathandre": _page("Lathandre"),
        }

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            return catalog[query]

        with (
            patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            cluster = await fetch_wiki_cluster(
                catalog["Padhiver"],
                depth=1,
                infobox_only=True,
            )

        self.assertEqual([page.title for page in cluster.pages], ["Padhiver", "Tymora"])
        self.assertFalse(cluster.truncated)

    async def test_bfs_stops_at_page_cap(self) -> None:
        catalog = {
            "Padhiver": _page("Padhiver", "Tymora", "Luskan"),
            "Tymora": _page("Tymora", "Lathandre"),
            "Luskan": _page("Luskan"),
            "Lathandre": _page("Lathandre"),
        }

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            return catalog[query]

        with (
            patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            cluster = await fetch_wiki_cluster(
                catalog["Padhiver"], limit=2, depth=8
            )

        self.assertEqual([page.title for page in cluster.pages], ["Padhiver", "Tymora"])
        self.assertTrue(cluster.truncated)


class TestFetchWikiPageSuggestions(unittest.IsolatedAsyncioTestCase):
    async def test_missing_page_does_not_recurse_on_same_suggestion(self) -> None:
        async def fake_api(params: dict[str, str]) -> dict:
            title = params.get("titles") or params.get("page") or "Ghost"
            return {"query": {"pages": [{"missing": True, "title": title}]}}

        with (
            patch("campaign.wiki._api_object", side_effect=fake_api),
            patch("campaign.wiki.suggest_pages", new=AsyncMock(return_value=["Ghost"])),
        ):
            with self.assertRaises(WikiNotFoundError):
                await fetch_wiki_page("Ghost")

    async def test_follows_one_different_suggestion_then_stops(self) -> None:
        async def fake_api(params: dict[str, str]) -> dict:
            title = params.get("titles") or params.get("page") or ""
            if title.casefold() == "neverwinter":
                return {"query": {"pages": [{"missing": True, "title": "Neverwinter"}]}}
            if params.get("action") == "parse":
                return {"parse": {"wikitext": "'''Padhiver''' est une cité."}}
            return {
                "query": {
                    "pages": [
                        {
                            "title": "Padhiver",
                            "fullurl": f"{WIKI_BASE}Padhiver",
                            "categories": [],
                        }
                    ]
                }
            }

        with (
            patch("campaign.wiki._api_object", side_effect=fake_api),
            patch(
                "campaign.wiki.suggest_pages",
                new=AsyncMock(return_value=["Neverwinter", "Padhiver"]),
            ),
        ):
            page = await fetch_wiki_page("Neverwinter")

        self.assertEqual(page.title, "Padhiver")
        self.assertEqual(page.suggested_from, "Neverwinter")

    async def test_import_root_does_not_follow_fuzzy_suggestions(self) -> None:
        suggest = AsyncMock(return_value=["Leilon"])

        async def fake_api(params: dict[str, str]) -> dict:
            return {"query": {"pages": [{"missing": True, "title": params.get("titles") or "Phandalin"}]}}

        with (
            patch("campaign.wiki._api_object", side_effect=fake_api),
            patch("campaign.wiki.suggest_pages", new=suggest),
        ):
            with self.assertRaises(WikiNotFoundError):
                await fetch_wiki_page("Phandalin", suggest=False)

        suggest.assert_not_called()

    async def test_cluster_skips_missing_links_without_suggestions(self) -> None:
        root = _page("Padhiver", "Ghost")
        calls: list[tuple[str, bool]] = []

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            calls.append((query, suggest))
            raise WikiNotFoundError(query)

        with (
            patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            cluster = await fetch_wiki_cluster(root, depth=1)

        self.assertEqual([page.title for page in cluster.pages], ["Padhiver"])
        self.assertEqual(calls, [("Ghost", False)])
        self.assertFalse(cluster.truncated)
        self.assertEqual(cluster.missing, ("Ghost",))
        self.assertEqual(cluster.failed, ())

    async def test_cluster_records_transient_failures(self) -> None:
        root = _page("Padhiver", "Tymora")

        async def fake_fetch(query: str, *, suggest: bool = True) -> WikiPage:
            raise WikiError("HTTP 503")

        with (
            patch("campaign.wiki.fetch_wiki_page", side_effect=fake_fetch),
            patch("campaign.wiki.asyncio.sleep", new_callable=AsyncMock),
        ):
            cluster = await fetch_wiki_cluster(root, depth=1)

        self.assertEqual([page.title for page in cluster.pages], ["Padhiver"])
        self.assertEqual(cluster.failed, ("Tymora",))
        self.assertEqual(cluster.missing, ())
