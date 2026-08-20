from pathlib import Path

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from config import PREFIX
from sheets.context import resolve_guild_id
from sheets.storage import get_character_name, get_sheet

GIF_PATH = Path(__file__).resolve().parent.parent / "assets" / "get_naked.gif"


def _actor_name(ctx: Context) -> str:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        return ctx.author.display_name
    sheet = get_sheet(user_id=ctx.author.id, guild_id=guild_id)
    if sheet is not None and sheet.name:
        return sheet.name
    stored = get_character_name(user_id=ctx.author.id, guild_id=guild_id)
    return stored or ctx.author.display_name


async def _send_dismay(ctx: Context) -> None:
    if not GIF_PATH.is_file():
        await command_reply(ctx, "The dismay gif is missing.")
        return
    name = _actor_name(ctx)
    await send_message(
        ctx,
        content=f"*{name} prend un air de désarroi.*",
        file=discord.File(GIF_PATH, filename="desarroi.gif"),
        definition_menu=False,
        linkify=False,
    )
    await delete_command(ctx)


def setup_fun(bot: Bot) -> None:
    @bot.hybrid_group(
        name="get",
        invoke_without_command=True,
        help=f"Show a gif of dismay. Usage: `{PREFIX}get naked`",
    )
    async def get_group(ctx: Context) -> None:
        await _send_dismay(ctx)

    @get_group.command(
        name="naked",
        aliases=["nu"],
        help="Show a gif of dismay.",
    )
    async def get_naked(ctx: Context) -> None:
        await _send_dismay(ctx)
