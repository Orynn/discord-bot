import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from config import PREFIX
from srd import fivetools
from srd.class_view import class_lookup_message
from srd.embeds import (
    armor_embed,
    background_embed,
    class_embed,
    condition_embed,
    feat_embed,
    item_embed,
    monster_embed,
    species_embed,
    spell_embed,
    weapon_embed,
)
from srd.fivetools.lookup import lookup_candidates, parse_search_query
from srd.search_view import SrdMatchView, build_match_prompt


async def _send_lookup(
    ctx: Context,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
) -> None:
    await send_message(ctx, embed=embed, view=view, definition_menu=view is None)
    await delete_command(ctx)


async def _handle_lookup_error(ctx: Context, exc: Exception) -> None:
    message = (
        str(exc)
        if isinstance(exc, fivetools.FiveToolsError)
        else "An unexpected error occurred."
    )
    await command_reply(ctx, message)
    await delete_command(ctx)


def setup_srd(bot: Bot) -> None:
    @bot.group(
        name="srd",
        invoke_without_command=True,
        help=f"Look up D&D rules. `{PREFIX}srd spell fireball` · `{PREFIX}help srd`",
    )
    async def srd_group(ctx: Context) -> None:
        from bot.help_commands import send_srd_help

        await send_srd_help(ctx)

    lookups = (
        ("spell", (), fivetools.search_spell, spell_embed, "Look up a spell"),
        (
            "species",
            ("race",),
            fivetools.search_species,
            species_embed,
            "Look up a species",
        ),
        ("class", (), fivetools.search_class, class_embed, "Look up a class"),
        (
            "background",
            (),
            fivetools.search_background,
            background_embed,
            "Look up a background",
        ),
        ("feat", (), fivetools.search_feat, feat_embed, "Look up a feat"),
        (
            "condition",
            ("cond",),
            fivetools.search_condition,
            condition_embed,
            "Look up a condition",
        ),
        (
            "monster",
            ("statblock", "creature"),
            fivetools.search_monster,
            monster_embed,
            "Look up a monster",
        ),
        ("weapon", (), fivetools.search_weapon, weapon_embed, "Look up a weapon"),
        ("armor", (), fivetools.search_armor, armor_embed, "Look up armor"),
        (
            "item",
            ("gear",),
            fivetools.search_item,
            item_embed,
            "Look up adventuring gear",
        ),
    )

    for name, aliases, search, embed_fn, title in lookups:

        @srd_group.command(
            name=name,
            aliases=list(aliases),
            help=f"{title}. Usage: `{PREFIX}srd {name} <name>`",
        )
        async def lookup_cmd(
            ctx: Context,
            *,
            query: str,
            _search=search,
            _embed=embed_fn,
            _kind=name,
        ) -> None:
            try:
                text, force_fuzzy = parse_search_query(query)
                if not text:
                    await _handle_lookup_error(
                        ctx, fivetools.FiveToolsNotFoundError("Missing search text.")
                    )
                    return
                candidates = lookup_candidates(_kind, text, force_list=force_fuzzy)
                if candidates is not None:
                    if not candidates:
                        raise fivetools.FiveToolsNotFoundError(
                            f"No {_kind} found matching '{text}'."
                        )
                    if len(candidates) > 1:
                        await send_message(
                            ctx,
                            embed=build_match_prompt(query=text, matches=candidates),
                            view=SrdMatchView(kind=_kind, matches=candidates),
                            definition_menu=False,
                        )
                        await delete_command(ctx)
                        return
                    item = await _search(query=str(candidates[0].get("name") or text))
                else:
                    item = await _search(query=text)
                if _kind == "class":
                    embed, view = class_lookup_message(item)
                    await _send_lookup(ctx, embed, view=view)
                    return
                await _send_lookup(ctx, embed=_embed(item))
            except fivetools.Open5eError as exc:
                await _handle_lookup_error(ctx, exc)
