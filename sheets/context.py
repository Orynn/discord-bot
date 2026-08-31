import re

import discord
from discord.ext.commands.context import Context

from bot.checks import is_staff, is_staff_user_id
from bot.command_helpers import SERVER_ONLY, command_reply
from bot.privacy import MISSING_PLAYER_TARGET, reject_other_player
from config import PREFIX
from players.discover import (
    discover_player_id,
    is_sandbox_owner_id,
    sandbox_player_id,
)
from sheets.data import CharacterSheet
from sheets.sandbox import ensure_sandbox_sheet
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
        raise ValueError(SERVER_ONLY)
    save_sheet(user_id=owner_id, guild_id=guild_id, sheet=sheet)


def parse_mention_and_text(
    ctx: Context, text: str
) -> tuple[discord.Member | None, str]:
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


def target_plain(member: discord.Member | None, sheet: CharacterSheet) -> str:
    if member is not None:
        return f"{sheet.name} ({member.display_name})"
    return sheet.name


def infer_player_id(ctx: Context) -> int | None:
    if ctx.guild is None:
        return None
    mock_id = sandbox_player_id(ctx.channel)
    if mock_id is not None:
        ensure_sandbox_sheet(guild_id=ctx.guild.id, user_id=mock_id)
        return mock_id
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

    mock_id = sandbox_player_id(ctx.channel)
    if mock_id is not None:
        if ctx.guild is not None:
            ensure_sandbox_sheet(guild_id=ctx.guild.id, user_id=mock_id)
        return mock_id

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
        await command_reply(ctx, SERVER_ONLY)
        return None

    if member is None and owner_id != ctx.author.id and ctx.guild is not None:
        found = ctx.guild.get_member(owner_id)
        if isinstance(found, discord.Member):
            member = found

    sheet = get_sheet(user_id=owner_id, guild_id=guild_id)
    if sheet is None and is_sandbox_owner_id(owner_id):
        sheet = ensure_sandbox_sheet(guild_id=guild_id, user_id=owner_id)
    if sheet is None:
        if missing_message:
            message = missing_message
        elif member is not None:
            message = (
                f"**{member.display_name}** n’a pas de fiche. "
                f"`{PREFIX}sheet create` d’abord."
            )
        elif owner_id != ctx.author.id:
            message = f"Ce joueur n’a pas de fiche. `{PREFIX}sheet create` d’abord."
        else:
            message = (
                f"Tu n’as pas de fiche. `{PREFIX}sheet create <nom>` d’abord."
            )
        await command_reply(ctx, message)
        return None

    return owner_id, sheet
