import re

import discord
from discord.ext.commands.context import Context

from bot.checks import is_staff, is_staff_user_id
from bot.command_helpers import command_reply
from bot.privacy import MISSING_PLAYER_TARGET, reject_other_player
from config import PREFIX
from players.discover import discover_player_id
from sheets.data import CharacterSheet
from sheets.storage import get_sheet, save_sheet


def format_skill_name(skill: str) -> str:
    return skill.replace("_", " ").title()


def resolve_guild_id(ctx: Context) -> int | None:
    if ctx.guild is not None:
        return ctx.guild.id
    from config import CAMPAIGN_GUILD_ID

    return CAMPAIGN_GUILD_ID


def save_owner_sheet(ctx: Context, owner_id: int, sheet: CharacterSheet) -> None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        raise ValueError("This command can only be used in a server.")
    save_sheet(user_id=owner_id, guild_id=guild_id, sheet=sheet)


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


def infer_player_id(ctx: Context) -> int | None:
    if ctx.guild is None:
        return None
    user_id = discover_player_id(guild=ctx.guild, channel=ctx.channel)
    if user_id is None:
        return None
    if is_staff(ctx) and (user_id == ctx.author.id or is_staff_user_id(user_id)):
        return None
    return user_id


async def resolve_owner(ctx: Context, member: discord.Member | None) -> int | None:
    if is_staff(ctx) and member is not None and member.id == ctx.author.id:
        member = None

    if member is not None:
        if not await reject_other_player(ctx, member):
            return None
        return member.id

    if is_staff(ctx):
        inferred = infer_player_id(ctx)
        if inferred is not None:
            return inferred
        await command_reply(ctx, MISSING_PLAYER_TARGET)
        return None

    return ctx.author.id


async def get_sheet_for_owner(
    ctx: Context,
    member: discord.Member | None,
    *,
    missing_message: str | None = None,
) -> tuple[int, CharacterSheet] | None:
    owner_id = await resolve_owner(ctx, member)
    if owner_id is None:
        return None

    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        await command_reply(ctx, "This command can only be used in a server.")
        return None

    if member is None and owner_id != ctx.author.id and ctx.guild is not None:
        found = ctx.guild.get_member(owner_id)
        if isinstance(found, discord.Member):
            member = found

    sheet = get_sheet(user_id=owner_id, guild_id=guild_id)
    if sheet is None:
        if member is not None:
            target = member.display_name
        elif owner_id != ctx.author.id:
            target = "That player"
        else:
            target = "You"
        message = missing_message or (
            f"{target} have no character sheet. Use `{PREFIX}sheet create <name>` first."
        )
        await command_reply(ctx, message)
        return None

    return owner_id, sheet
