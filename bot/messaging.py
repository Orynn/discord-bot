from discord.abc import Messageable
from discord.ext.commands.context import Context

import discord

from srd.definition_view import build_definition_view
from srd.embeds import clamp_embed_limits
from srd.glossary import is_loaded
from srd.linkify import linkify_embed, linkify_embeds, linkify_text, mentioned_entries


def prepare_outgoing(
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    linkify: bool = True,
    definition_menu: bool = True,
    view: discord.ui.View | None = None,
) -> tuple[str | None, discord.Embed | None, list[discord.Embed] | None, discord.ui.View | None]:
    prepared_content = content
    prepared_embed = embed
    prepared_embeds = embeds
    prepared_view = view

    if linkify and is_loaded():
        if prepared_content:
            prepared_content = linkify_text(prepared_content)
        if prepared_embed:
            prepared_embed = linkify_embed(prepared_embed)
        if prepared_embeds:
            prepared_embeds = linkify_embeds(prepared_embeds)

    if prepared_embed is not None:
        prepared_embed = clamp_embed_limits(prepared_embed)
    if prepared_embeds is not None:
        prepared_embeds = [clamp_embed_limits(item) for item in prepared_embeds]

    if definition_menu and is_loaded() and prepared_view is None:
        entries = mentioned_entries(
            content=content,
            embed=embed,
            embeds=embeds,
        )
        prepared_view = build_definition_view(entries=entries)

    return prepared_content, prepared_embed, prepared_embeds, prepared_view


def _embed_kwargs(
    embed: discord.Embed | None,
    embeds: list[discord.Embed] | None,
) -> dict[str, discord.Embed | list[discord.Embed]]:
    if embeds is not None:
        return {"embeds": embeds}
    if embed is not None:
        return {"embed": embed}
    return {}


def _view_kwargs(
    *,
    prepared_view: discord.ui.View | None,
    had_view: bool = False,
    edit: bool = False,
) -> dict[str, discord.ui.View | None]:
    if prepared_view is not None:
        return {"view": prepared_view}
    if edit and had_view:
        return {"view": None}
    return {}


async def send_message(
    target: Context | Messageable,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    linkify: bool = True,
    definition_menu: bool = True,
    **kwargs,
) -> discord.Message:
    prepared_content, prepared_embed, prepared_embeds, prepared_view = prepare_outgoing(
        content=content,
        embed=embed,
        embeds=embeds,
        linkify=linkify,
        definition_menu=definition_menu,
        view=kwargs.get("view"),
    )

    send_kwargs = dict(kwargs)
    send_kwargs.pop("view", None)
    send_kwargs.update(_view_kwargs(prepared_view=prepared_view))

    if isinstance(target, Context):
        return await target.send(
            content=prepared_content,
            **_embed_kwargs(prepared_embed, prepared_embeds),
            **send_kwargs,
        )

    return await target.send(
        content=prepared_content,
        **_embed_kwargs(prepared_embed, prepared_embeds),
        **send_kwargs,
    )


async def send_interaction_message(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
    linkify: bool = True,
    definition_menu: bool = True,
    ephemeral: bool = False,
    edit: bool = False,
    **kwargs,
) -> discord.Message | None:
    prepared_content, prepared_embed, prepared_embeds, prepared_view = prepare_outgoing(
        content=content,
        embed=embed,
        embeds=embeds,
        linkify=linkify,
        definition_menu=definition_menu,
        view=kwargs.get("view"),
    )

    send_kwargs = dict(kwargs)
    send_kwargs.pop("view", None)
    send_kwargs.update(
        _view_kwargs(
            prepared_view=prepared_view,
            had_view="view" in kwargs,
            edit=edit,
        )
    )
    if ephemeral:
        send_kwargs["ephemeral"] = True

    embed_kwargs = _embed_kwargs(prepared_embed, prepared_embeds)

    if edit:
        await interaction.response.edit_message(
            content=prepared_content,
            **embed_kwargs,
            **send_kwargs,
        )
        return interaction.message

    if interaction.response.is_done():
        return await interaction.followup.send(
            content=prepared_content,
            **embed_kwargs,
            wait=True,
            **send_kwargs,
        )

    await interaction.response.send_message(
        content=prepared_content,
        **embed_kwargs,
        **send_kwargs,
    )
    return await interaction.original_response()


async def send_reply(
    ctx: Context,
    message: str,
    *,
    linkify: bool = True,
    definition_menu: bool = True,
) -> None:
    await send_message(
        ctx,
        content=message,
        linkify=linkify,
        definition_menu=definition_menu,
    )
