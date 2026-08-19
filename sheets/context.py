import re

import discord
from discord.ext.commands.context import Context

from bot.checks import is_admin
from bot.command_helpers import command_reply
from config import PREFIX
from sheets.data import CharacterSheet
from sheets.storage import get_sheet


def format_skill_name(skill: str) -> str:
    return skill.replace("_", " ").title()


def parse_mention_and_text(ctx: Context, text: str) -> tuple[discord.Member | None, str]:
    member = None
    mentions = getattr(getattr(ctx, "message", None), "mentions", None) or []
    if mentions:
        member = mentions[0]
    match = re.search(r"<@!?(\d+)>", text)
    if match:
        user_id = int(match.group(1))
        if member is None and ctx.guild is not None:
            found = ctx.guild.get_member(user_id)
            if isinstance(found, discord.Member):
                member = found
    cleaned = re.sub(r"<@!?\d+>", "", text).strip()
    return member, cleaned


def target_label(member: discord.Member | None, sheet: CharacterSheet) -> str:
    if member is not None:
        return f"**{sheet.name}** ({member.display_name})"
    return f"**{sheet.name}**"


async def resolve_owner(ctx: Context, member: discord.Member | None) -> int | None:
    if member is None or member.id == ctx.author.id:
        return ctx.author.id
    if not is_admin(ctx):
        await command_reply(ctx, "Only admins can manage another player's character sheet.")
        return None
    return member.id


async def get_sheet_for_owner(
    ctx: Context,
    member: discord.Member | None,
    *,
    missing_message: str | None = None,
) -> tuple[int, CharacterSheet] | None:
    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        return None

    sheet = get_sheet(user_id=owner_id)
    if sheet is None:
        target = member.display_name if member else "You"
        message = missing_message or (
            f"{target} have no character sheet. Use `{PREFIX}sheet create <name>` first."
        )
        await command_reply(ctx, message)
        return None

    return owner_id, sheet
