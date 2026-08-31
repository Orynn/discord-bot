import re

import discord
from discord import app_commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from config import PREFIX
from sheets.context import parse_mention_and_text, resolve_guild_id, resolve_owner
from sheets.data import CharacterSheet
from sheets.dice import (
    ParsedRollRequest,
    apply_roll_options,
    execute_roll,
    format_roll_embed,
    parse_advantage_flag,
    parse_roll_args,
    validate_roll_request,
)
from sheets.storage import get_sheet, save_sheet

ROLL_HELP = command_help(
    "Jets de dés, avec les bonus de la fiche si tu en as une.",
    f"`{PREFIX}roll [dés|compétence] [adv|dis]`",
    f"`{PREFIX}roll 1d20` — jet simple",
    f"`{PREFIX}roll 2d6+3` — modificateur fixe",
    f"`{PREFIX}roll 1d20 str` — caractéristique de la fiche",
    f"`{PREFIX}roll athletics` · `{PREFIX}roll discrétion` — compétence (1d20)",
    f"`{PREFIX}roll dex save` · `{PREFIX}roll sauvegarde sag` — sauvegarde",
    f"`{PREFIX}roll adv perception` · `{PREFIX}roll investigation advantage`",
    f"`{PREFIX}roll @joueur athletics` — staff seulement",
    "`/roll` — mêmes jets, plus les options `bonus` et `avantage`",
)

_ADVANTAGE_CHOICES = [
    app_commands.Choice(name="Avantage", value="advantage"),
    app_commands.Choice(name="Désavantage", value="disadvantage"),
]


def _clean_roll_args(args: str) -> str:
    return re.sub(r"<@!?\d+>", "", args).strip()


async def _resolve_roll_target(
    ctx: Context,
    member: discord.Member | None,
) -> tuple[int, CharacterSheet | None, str] | None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        await command_reply(ctx, "Cette commande marche seulement sur le serveur.")
        return None

    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        return None

    sheet = get_sheet(user_id=owner_id, guild_id=guild_id)
    if member is None and ctx.guild is not None and owner_id != ctx.author.id:
        found = ctx.guild.get_member(owner_id)
        if isinstance(found, discord.Member):
            member = found

    if member is not None and member.id != ctx.author.id:
        if sheet is None:
            await command_reply(
                ctx, f"**{member.display_name}** n’a pas de fiche."
            )
            return None
        return owner_id, sheet, f"**{sheet.name}** ({member.display_name})"

    label = f"**{sheet.name}**" if sheet else f"**{ctx.author.display_name}**"
    return owner_id, sheet, label


def _avantage_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, app_commands.Choice):
        raw = value.value
        return str(raw) if raw is not None else None
    text = str(value).strip()
    return text or None


def prepare_roll_request(
    args: str,
    *,
    bonus: int | None = None,
    avantage: object = None,
) -> ParsedRollRequest | None:
    option_adv = parse_advantage_flag(_avantage_value(avantage))
    cleaned = args.strip()
    if not cleaned:
        if bonus is None and option_adv is None:
            return None
        cleaned = "1d20"
    request = parse_roll_args(cleaned)
    request = apply_roll_options(request, bonus=bonus, advantage=option_adv)
    validate_roll_request(request)
    return request


def setup_roll(bot: Bot) -> None:
    @bot.hybrid_command(
        name="roll",
        aliases=["r"],
        help=ROLL_HELP,
    )
    @app_commands.describe(
        member="Player whose sheet to use (staff)",
        args="Dice or skill, e.g. athletics, 2d6+3",
        bonus="Flat bonus to add, e.g. 2 or -1",
        avantage="Roll with advantage or disadvantage",
    )
    @app_commands.choices(avantage=_ADVANTAGE_CHOICES)
    async def roll_command(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
        bonus: int | None = None,
        avantage: str | None = None,
    ) -> None:
        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        else:
            args = _clean_roll_args(args)

        try:
            request = prepare_roll_request(args, bonus=bonus, avantage=avantage)
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return
        if request is None:
            await ctx.send_help(ctx.command)
            return

        target = await _resolve_roll_target(ctx, member)
        if target is None:
            return
        owner_id, sheet, roller_label = target
        guild_id = resolve_guild_id(ctx)

        try:
            result = execute_roll(
                dice=request.dice,
                sheet=sheet,
                modifier_tokens=request.modifier_tokens,
                advantage=request.advantage,
            )
        except ValueError as exc:
            await command_reply(ctx, str(exc))
            return

        if result.spent_inspiration and sheet is not None and guild_id is not None:
            save_sheet(user_id=owner_id, guild_id=guild_id, sheet=sheet)

        await send_message(
            ctx,
            embed=format_roll_embed(result, roller_label=roller_label),
        )
        await delete_command(ctx)
