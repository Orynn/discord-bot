import re

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from config import PREFIX
from sheets.context import parse_mention_and_text
from sheets.data import CharacterSheet
from sheets.dice import execute_roll, format_roll_embed, parse_roll_args, validate_roll_request
from sheets.storage import get_sheet


def _clean_roll_args(args: str) -> str:
    return re.sub(r"<@!?\d+>", "", args).strip()


async def _resolve_roll_target(
    ctx: Context,
    member: discord.Member | None,
) -> tuple[int, CharacterSheet | None, str] | None:
    if member is None:
        sheet = get_sheet(user_id=ctx.author.id)
        label = f"**{sheet.name}**" if sheet else f"**{ctx.author.display_name}**"
        return ctx.author.id, sheet, label

    if not is_admin(ctx):
        await command_reply(ctx, "Only admins can roll for another player.")
        return None

    sheet = get_sheet(user_id=member.id)
    if sheet is None:
        await command_reply(ctx, f"**{member.display_name}** has no character sheet.")
        return None

    return member.id, sheet, f"**{sheet.name}** ({member.display_name})"


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
            admin_hint = f"\n`{PREFIX}roll @player 1d20 perception` — admin only" if is_admin(ctx) else ""
            await command_reply(
                ctx,
                (
                    f"**Roll commands:**\n"
                    f"`{PREFIX}roll 1d20` — plain roll\n"
                    f"`{PREFIX}roll 2d6+3` — roll with flat modifier\n"
                    f"`{PREFIX}roll 1d20 str` — ability modifier from your sheet\n"
                    f"`{PREFIX}roll athletics` — skill check (defaults to 1d20)\n"
                    f"`{PREFIX}roll dex save` · `{PREFIX}roll save wis` — saving throw\n"
                    f"`{PREFIX}roll adv 1d20 perception` · `{PREFIX}roll dis stealth`"
                    f"{admin_hint}"
                ),
            )
            await delete_command(ctx)
            return

        target = await _resolve_roll_target(ctx, member)
        if target is None:
            return
        _, sheet, roller_label = target

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

        await send_message(
            ctx,
            embed=format_roll_embed(result, roller_label=roller_label),
        )
        await delete_command(ctx)
