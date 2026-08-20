from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord

from bot.messaging import send_interaction_message
from srd import fivetools
from srd.embeds import (
    armor_embed,
    item_embed,
    monster_embed,
    species_embed,
    weapon_embed,
)

_KIND_PRESENTERS: dict[str, tuple[Callable[[str], Awaitable[dict[str, Any]]], Callable[[dict[str, Any]], discord.Embed]]] = {
    "species": (lambda slug: fivetools.get_species(slug=slug), species_embed),
    "weapon": (lambda slug: fivetools.get_weapon(slug=slug), weapon_embed),
    "armor": (lambda slug: fivetools.get_armor(slug=slug), armor_embed),
    "item": (lambda slug: fivetools.get_item(slug=slug), item_embed),
    "monster": (lambda slug: fivetools.get_monster(slug=slug), monster_embed),
}


def _option_label(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "Unknown")
    source = str(item.get("source") or "")
    if source and len(name) < 80:
        return f"{name} ({source})"[:100]
    return name[:100]


class SrdMatchSelect(discord.ui.Select):
    def __init__(self, *, kind: str, matches: list[dict[str, Any]]) -> None:
        self._kind = kind
        options = [
            discord.SelectOption(
                label=_option_label(item),
                value=str(item.get("slug") or item.get("name") or "")[:100],
                description=str(item.get("source") or kind)[:100],
            )
            for item in matches[:25]
            if item.get("slug") or item.get("name")
        ]
        super().__init__(
            placeholder=f"Choose a {kind}…",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        presenter = _KIND_PRESENTERS.get(self._kind)
        if presenter is None:
            await send_interaction_message(interaction, content="Unknown lookup type.", ephemeral=True)
            return
        getter, embed_fn = presenter
        try:
            item = await getter(self.values[0])
        except fivetools.FiveToolsError as exc:
            await send_interaction_message(interaction, content=str(exc), ephemeral=True)
            return
        await send_interaction_message(
            interaction,
            embed=embed_fn(item),
            edit=True,
            view=None,
            definition_menu=False,
        )


class SrdMatchView(discord.ui.View):
    def __init__(self, *, kind: str, matches: list[dict[str, Any]]) -> None:
        super().__init__(timeout=180)
        self.add_item(SrdMatchSelect(kind=kind, matches=matches))


def build_match_prompt(*, query: str, matches: list[dict[str, Any]]) -> discord.Embed:
    lines: list[str] = []
    for item in matches[:12]:
        name = str(item.get("name") or "?")
        source = str(item.get("source") or "")
        extra = f" · {source}" if source else ""
        lines.append(f"• **{name}**{extra}")
    extra_count = len(matches) - 12
    if extra_count > 0:
        lines.append(f"… +{extra_count} more in the menu")
    return discord.Embed(
        title="🔎 Several matches",
        description=f"Query: `{query}`\nChoose one:\n" + "\n".join(lines),
        color=0x4A6741,
    )
