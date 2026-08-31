from __future__ import annotations

import discord

from srd.embeds import kind_embed_color, class_embed, clean_markdown, truncate

_FEATURE_PAGE_LIMIT = 1800


def _packed_feature_pages(features: list[dict]) -> list[tuple[str, str]]:
    pages: list[tuple[str, str]] = []
    chunks: list[str] = []
    start_level: int | None = None
    end_level: int | None = None
    size = 0

    def flush() -> None:
        nonlocal chunks, start_level, end_level, size
        if not chunks or start_level is None:
            return
        title = (
            f"Level {start_level}"
            if start_level == end_level
            else f"Levels {start_level}–{end_level}"
        )
        pages.append((title, "\n\n".join(chunks)))
        chunks = []
        start_level = None
        end_level = None
        size = 0

    for feature in features:
        level = int(feature.get("level") or 0)
        block = f"**Level {level} — {feature['name']}**\n{feature.get('desc') or ''}".strip()
        if chunks and size + len(block) + 2 > _FEATURE_PAGE_LIMIT:
            flush()
        if not chunks:
            start_level = level
        end_level = level
        chunks.append(block)
        size += len(block) + 2
    flush()
    return pages


def build_class_pages(
    char_class: dict, subclass: dict | None = None
) -> list[discord.Embed]:
    pages = [class_embed(char_class, subclass=subclass)]
    source_title = char_class.get("document__title", "5etools")
    url = (subclass or char_class).get("url") or char_class.get("url")

    for title, body in _packed_feature_pages(char_class.get("features") or []):
        pages.append(
            discord.Embed(
                title=f"{char_class['name']} — {title}",
                description=truncate(clean_markdown(body), 4000),
                color=kind_embed_color("class"),
                url=url,
            )
        )

    if subclass is None:
        archetypes = char_class.get("archetypes") or []
        if len(archetypes) > 6:
            lines = []
            for entry in archetypes:
                name = entry.get("name")
                if not name:
                    continue
                desc = truncate(clean_markdown(entry.get("desc") or ""), 280)
                lines.append(f"**{name}**\n{desc}" if desc else f"**{name}**")
            pages.append(
                discord.Embed(
                    title=f"{char_class['name']} — Subclasses",
                    description=truncate("\n\n".join(lines), 4000),
                    color=kind_embed_color("class"),
                    url=url,
                )
            )

    total = len(pages)
    for index, embed in enumerate(pages):
        embed.set_footer(text=f"{source_title} · {index + 1}/{total}")
    return pages


class ClassPagesView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]) -> None:
        super().__init__(timeout=300)
        self.pages = pages
        self.index = 0
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.prev_page.disabled = self.index <= 0
        self.next_page.disabled = self.index >= len(self.pages) - 1

    async def _show(self, interaction: discord.Interaction) -> None:
        from bot.messaging import send_interaction_message

        self._sync_buttons()
        await send_interaction_message(
            interaction,
            embed=self.pages[self.index],
            view=self,
            edit=True,
            definition_menu=False,
        )

    @discord.ui.button(label="Prev", style=discord.ButtonStyle.secondary)
    async def prev_page(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        self.index = max(0, self.index - 1)
        await self._show(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next_page(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._show(interaction)


def class_lookup_message(
    char_class: dict,
    subclass: dict | None = None,
) -> tuple[discord.Embed, ClassPagesView | None]:
    pages = build_class_pages(char_class, subclass=subclass)
    if len(pages) <= 1:
        return pages[0], None
    return pages[0], ClassPagesView(pages)
