import re

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_staff
from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from config import PREFIX
from sheets.context import parse_mention_and_text, resolve_guild_id, resolve_owner
from sheets.data import CharacterSheet
from sheets.dice import (
    execute_roll,
    format_roll_embed,
    parse_roll_args,
    validate_roll_request,
)
from sheets.storage import get_sheet, save_sheet


def _clean_roll_args(args: str) -> str:
    return re.sub(r"<@!?\d+>", "", args).strip()


async def _resolve_roll_target(
    ctx: Context,
    member: discord.Member | None,
) -> tuple[int, CharacterSheet | None, str] | None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        await command_reply(ctx, "This command can only be used in a server.")
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
                ctx, f"**{member.display_name}** has no character sheet."
            )
            return None
        return owner_id, sheet, f"**{sheet.name}** ({member.display_name})"

    label = f"**{sheet.name}**" if sheet else f"**{ctx.author.display_name}**"
    return owner_id, sheet, label


def setup_roll(bot: Bot) -> None:
    @bot.hybrid_command(
        name="roll",
        aliases=["r"],
        help="Roll dice with optional sheet modifiers (1d20, athletics, adv dex save).",
    )
    async def roll_command(
        ctx: Context,
        member: discord.Member | None = None,
        *,
        args: str = "",
    ) -> None:
        if member is None:
            member, args = parse_mention_and_text(ctx, args)
        else:
            args = _clean_roll_args(args)

        if not args:
            admin_hint = (
                f"\n`{PREFIX}roll @player 1d20 perception` — admin only"
                if is_staff(ctx)
                else ""
            )
            await command_reply(
                ctx,
                (
                    f"**Roll commands:**\n"
                    f"`{PREFIX}roll 1d20` — plain roll\n"
                    f"`{PREFIX}roll 2d6+3` — roll with flat modifier\n"
                    f"`{PREFIX}roll 1d20 str` — ability modifier from your sheet\n"
                    f"`{PREFIX}roll athletics` · `{PREFIX}roll discrétion` — skill check (defaults to 1d20)\n"
                    f"`{PREFIX}roll dex save` · `{PREFIX}roll sauvegarde sag` — saving throw\n"
                    f"`{PREFIX}roll adv 1d20 perception` · `{PREFIX}roll avantage discrétion`"
                    f"{admin_hint}"
                ),
            )
            await delete_command(ctx)
            return

        target = await _resolve_roll_target(ctx, member)
        if target is None:
            return
        owner_id, sheet, roller_label = target
        guild_id = resolve_guild_id(ctx)

        try:
            request = parse_roll_args(args)
            validate_roll_request(request)
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
