import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.help_text import command_help
from config import PREFIX
from sheets.commands.core import handle_hp
from sheets.commands.slots import handle_slots_spec
from sheets.commands.status import (
    handle_rest_spec,
    handle_short_rest_spec,
    perform_long_rest,
)


def setup_everyday_shortcuts(bot: Bot) -> None:
    @bot.hybrid_command(
        name="hp",
        aliases=["pv"],
        help=command_help(
            "Change les PV : relatif (`-4`, `+6`) ou valeur (`12`, `12/20`).",
            f"`{PREFIX}hp -4`",
            f"`{PREFIX}hp +6` · `{PREFIX}hp 12` (valeur) · `{PREFIX}hp 12/20`",
        ),
    )
    async def hp_command(ctx: Context, *, spec: str = "") -> None:
        await handle_hp(ctx, spec)

    @bot.hybrid_command(
        name="slots",
        aliases=["slot"],
        help=command_help(
            "Dépense un emplacement de sorts, ou affiche le reste.",
            f"`{PREFIX}slots 1`",
            f"`{PREFIX}slots 2 2` — deux emplacements de niveau 2",
        ),
    )
    async def slots_command(ctx: Context, *, spec: str = "") -> None:
        await handle_slots_spec(ctx, spec)

    @bot.hybrid_group(
        name="rest",
        aliases=["repos"],
        invoke_without_command=True,
        help=command_help(
            "Prend un repos court ou long.",
            f"`{PREFIX}rest long`",
            f"`{PREFIX}rest short [dés]`",
        ),
    )
    async def rest_group(ctx: Context, *, spec: str = "") -> None:
        await handle_rest_spec(ctx, spec)

    @rest_group.command(
        name="long",
        help=command_help(
            "Repos long : PV, dés de vie, emplacements, +8 h sur l’horloge.",
            f"`{PREFIX}rest long [@joueur]`",
        ),
    )
    async def rest_long(ctx: Context, member: discord.Member | None = None) -> None:
        await perform_long_rest(ctx, member)

    @rest_group.command(
        name="short",
        help=command_help(
            "Repos court. Les emplacements de pacte du warlock reviennent.",
            f"`{PREFIX}rest short [@joueur] [dés]`",
        ),
    )
    async def rest_short(ctx: Context, *, spec: str = "") -> None:
        await handle_short_rest_spec(ctx, spec)
