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


async def _send_lookup(
    ctx: Context,
    embed: discord.Embed,
    *,
    view: discord.ui.View | None = None,
) -> None:
    await send_message(ctx, embed=embed, view=view, definition_menu=view is None)
    await delete_command(ctx)


async def _handle_lookup_error(ctx: Context, exc: Exception) -> None:
    message = str(exc) if isinstance(exc, fivetools.FiveToolsError) else "An unexpected error occurred."
    await command_reply(ctx, message)
    await delete_command(ctx)


def setup_srd(bot: Bot) -> None:
    @bot.group(
        name="srd",
        invoke_without_command=True,
        help=f"Look up D&D rules content via 5etools. Usage: `{PREFIX}srd <type> <name>`",
    )
    async def srd_group(ctx: Context) -> None:
        await command_reply(
            ctx,
            "**Rules lookups (5etools):**\n"
            f"`{PREFIX}srd spell <name>` — spell details\n"
            f"`{PREFIX}srd species <name>` — species traits\n"
            f"`{PREFIX}srd class <name>` — class features\n"
            f"`{PREFIX}srd background <name>` — background\n"
            f"`{PREFIX}srd feat <name>` — feat\n"
            f"`{PREFIX}srd condition <name>` — condition\n"
            f"`{PREFIX}srd monster <name>` — statblock\n"
            f"`{PREFIX}srd weapon <name>` — weapon\n"
            f"`{PREFIX}srd armor <name>` — armor\n"
            f"`{PREFIX}srd item <name>` — adventuring gear",
        )
        await delete_command(ctx)

    lookups = (
        ("spell", (), fivetools.search_spell, spell_embed, "Look up a spell"),
        ("species", ("race",), fivetools.search_species, species_embed, "Look up a species"),
        ("class", (), fivetools.search_class, class_embed, "Look up a class"),
        ("background", (), fivetools.search_background, background_embed, "Look up a background"),
        ("feat", (), fivetools.search_feat, feat_embed, "Look up a feat"),
        ("condition", ("cond",), fivetools.search_condition, condition_embed, "Look up a condition"),
        ("monster", ("statblock", "creature"), fivetools.search_monster, monster_embed, "Look up a monster"),
        ("weapon", (), fivetools.search_weapon, weapon_embed, "Look up a weapon"),
        ("armor", (), fivetools.search_armor, armor_embed, "Look up armor"),
        ("item", ("gear",), fivetools.search_item, item_embed, "Look up adventuring gear"),
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
                item = await _search(query=query.strip())
                if _kind == "class":
                    embed, view = class_lookup_message(item)
                    await _send_lookup(ctx, embed, view=view)
                    return
                await _send_lookup(ctx, embed=_embed(item))
            except fivetools.Open5eError as exc:
                await _handle_lookup_error(ctx, exc)
