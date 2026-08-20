import unittest

import discord

from bot.messaging import _embed_kwargs, _view_kwargs, prepare_outgoing
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


class TestViewKwargs(unittest.TestCase):
    def test_omits_none_for_new_messages(self) -> None:
        assert _view_kwargs(prepared_view=None, had_view=True, edit=False) == {}

    def test_keeps_none_when_editing_to_clear_view(self) -> None:
        assert _view_kwargs(prepared_view=None, had_view=True, edit=True) == {"view": None}

    def test_includes_prepared_view(self) -> None:
        view = discord.ui.View()
        assert _view_kwargs(prepared_view=view) == {"view": view}


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

    def test_clamps_linkified_embed_fields_to_discord_limit(self) -> None:
        from srd.embeds import DISCORD_FIELD_LIMIT
        from srd.linkify import linkify_embed

        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        embed = discord.Embed(title="Lich")
        embed.add_field(name="🔮 Spellcasting", value=("Fireball " * 120).strip(), inline=False)
        linked = linkify_embed(embed)
        assert any(len(field.value) > DISCORD_FIELD_LIMIT for field in linked.fields)

        _, prepared, _, _ = prepare_outgoing(embed=embed)
        assert prepared is not None
        assert prepared.fields
        for field in prepared.fields:
            assert len(field.value) <= DISCORD_FIELD_LIMIT
        assert any("Fireball" in field.value for field in prepared.fields)

    def test_skips_inline_code(self) -> None:
        from srd.linkify import linkify_text

        glossary.register_item(name="Fireball", kind="spell", slug="fireball")
        glossary._store.loaded = True
        glossary._store.rebuild_index()

        text = linkify_text("Use `;srd spell fireball` then Cast Fireball.")
        assert "`;srd spell fireball`" in text
        assert "[Fireball]" in text
        assert "5e.tools" in text
