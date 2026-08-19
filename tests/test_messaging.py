import discord

from bot.messaging import _embed_kwargs, prepare_outgoing
from srd import glossary
from srd.linkify import markdown_link


class TestMarkdownLink:
    def test_encodes_underscores_in_url(self) -> None:
        link = markdown_link("Fireball", "https://5e.tools/spells.html#fireball_xphb")
        assert link == "[Fireball](https://5e.tools/spells.html#fireball%5Fxphb)"
        assert "_xphb" not in link.split("]", 1)[1]


class TestEmbedKwargs:
    def test_prefers_embeds_when_both_provided(self) -> None:
        embed = discord.Embed(title="one")
        embeds = [discord.Embed(title="many")]
        assert _embed_kwargs(embed, embeds) == {"embeds": embeds}

    def test_uses_embed_when_only_embed_provided(self) -> None:
        embed = discord.Embed(title="one")
        assert _embed_kwargs(embed, None) == {"embed": embed}

    def test_uses_embeds_when_only_embeds_provided(self) -> None:
        embeds = [discord.Embed(title="many")]
        assert _embed_kwargs(None, embeds) == {"embeds": embeds}

    def test_returns_empty_when_no_embeds(self) -> None:
        assert _embed_kwargs(None, None) == {}


class TestPrepareOutgoing:
    def setup_method(self) -> None:
        glossary.reset_store()

    def test_linkifies_content_when_glossary_loaded(self) -> None:
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        content, _, _, _ = prepare_outgoing(content="Cast Fireball at the goblin.")
        assert content is not None
        assert "[Fireball]" in content
        assert "5e.tools" in content
        assert "](https://5e.tools" in content
        assert "_xphb" not in content or "%5F" in content

    def test_skips_definition_menu_when_view_provided(self) -> None:
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        view = discord.ui.View()
        _, _, _, prepared_view = prepare_outgoing(
            content="Fireball",
            view=view,
            definition_menu=True,
        )
        assert prepared_view is view

    def test_adds_definition_menu_for_mentions(self) -> None:
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        _, _, _, prepared_view = prepare_outgoing(content="Cast Fireball.")
        assert prepared_view is not None
        assert len(prepared_view.children) == 1

    def test_respects_linkify_false(self) -> None:
        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        content, _, _, _ = prepare_outgoing(content="Cast Fireball.", linkify=False)
        assert content == "Cast Fireball."
