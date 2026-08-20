from typing import Any

import discord

from bot.help_text import HELP_COLOR
from bot.messaging import send_message
from config import (
    PLAYER_CATEGORY_EMOJI,
    PLAYER_CATEGORY_WIDTH,
    PLAYER_CHANNEL_OOC,
    PLAYER_CHANNEL_RP,
    PREFIX,
)
from campaign.forums import add_staff_channel_overwrites
from players.format import format_player_category_name
from players.storage import delete_player_section, save_player_section
from sheets.data import CharacterSheet
from sheets.storage import get_sheet, save_sheet, set_character_name


class PlayerSetupError(Exception):
    pass


def ensure_player_sheet(*, user_id: int, guild_id: int, name: str) -> tuple[CharacterSheet, bool]:
    """Create or update the player's sheet and speaking name. Returns (sheet, created)."""
    cleaned = name.strip()
    if not cleaned:
        raise PlayerSetupError("Character name cannot be empty.")

    existing = get_sheet(user_id=user_id, guild_id=guild_id)
    if existing is not None:
        if existing.name != cleaned:
            existing.name = cleaned
            save_sheet(user_id=user_id, guild_id=guild_id, sheet=existing)
        set_character_name(user_id=user_id, guild_id=guild_id, name=cleaned)
        return existing, False

    sheet = CharacterSheet(name=cleaned)
    save_sheet(user_id=user_id, guild_id=guild_id, sheet=sheet)
    set_character_name(user_id=user_id, guild_id=guild_id, name=cleaned)
    return sheet, True


def build_welcome_embed(*, character_name: str, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎉 Welcome, {character_name}!",
        description=f"Your private section is ready, {member.mention}.",
        color=HELP_COLOR,
    )
    embed.add_field(
        name="💬 Channels",
        value=(
            f"• **{PLAYER_CHANNEL_OOC}** — out-of-character chat, questions, dice\n"
            f"• **{PLAYER_CHANNEL_RP}** — in-character roleplay (`{PREFIX}pc`, `{PREFIX}desc`)"
        ),
        inline=False,
    )
    embed.add_field(
        name="🚀 Getting started",
        value=(
            f"`{PREFIX}sheet show` — your character sheet\n"
            f"`{PREFIX}sheet set class <class>` · `{PREFIX}sheet set level <n>`\n"
            f"`{PREFIX}sheet import` — import a D&D Beyond PDF\n"
            f"`{PREFIX}srd spell <name>` — 5etools rules lookup\n"
            f"`{PREFIX}help` — full command list"
        ),
        inline=False,
    )
    embed.set_footer(text="Have fun at the table!")
    return embed


def _member_overwrites(
    guild: discord.Guild,
    member: discord.Member,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            embed_links=True,
            use_external_emojis=True,
            add_reactions=True,
        ),
    }
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_messages=True,
            read_message_history=True,
        )
    staff_visibility = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        manage_messages=True,
        attach_files=True,
        embed_links=True,
    )
    add_staff_channel_overwrites(guild, overwrites, staff_visibility)
    return overwrites


async def create_player_section(
    *,
    guild: discord.Guild,
    member: discord.Member,
    display_name: str,
) -> dict[str, Any]:
    if not guild.me or not guild.me.guild_permissions.manage_channels:
        raise PlayerSetupError("I need the **Manage Channels** permission to create player sections.")

    character_name = display_name.strip()
    if not character_name:
        raise PlayerSetupError("Character name cannot be empty.")

    _, sheet_created = ensure_player_sheet(user_id=member.id, guild_id=guild.id, name=character_name)

    category_name = format_player_category_name(
        character_name,
        width=PLAYER_CATEGORY_WIDTH,
        emoji=PLAYER_CATEGORY_EMOJI,
    )
    if len(category_name) > 100:
        raise PlayerSetupError("Category name is too long for Discord. Shorten the player name or config width.")

    overwrites = _member_overwrites(guild, member)
    category = await guild.create_category(name=category_name, overwrites=overwrites)
    ooc_channel = await guild.create_text_channel(
        name=PLAYER_CHANNEL_OOC,
        category=category,
        overwrites=overwrites,
    )
    rp_channel = await guild.create_text_channel(
        name=PLAYER_CHANNEL_RP,
        category=category,
        overwrites=overwrites,
    )

    await send_message(ooc_channel, embed=build_welcome_embed(character_name=character_name, member=member))

    record = {
        "name": character_name.upper(),
        "category_id": category.id,
        "ooc_channel_id": ooc_channel.id,
        "roleplay_channel_id": rp_channel.id,
        "sheet_created": sheet_created,
    }
    save_player_section(guild_id=guild.id, user_id=member.id, data=record)
    return record


async def remove_player_section(
    *,
    guild: discord.Guild,
    user_id: int,
) -> dict[str, Any]:
    if not guild.me or not guild.me.guild_permissions.manage_channels:
        raise PlayerSetupError("I need the **Manage Channels** permission to remove player sections.")

    record = delete_player_section(guild_id=guild.id, user_id=user_id)
    if record is None:
        raise PlayerSetupError("That player has no registered section.")

    channel_ids = [
        record.get("ooc_channel_id"),
        record.get("roleplay_channel_id"),
    ]
    for channel_id in channel_ids:
        if not channel_id:
            continue
        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            await channel.delete(reason="Player section removed")

    category_id = record.get("category_id")
    if category_id:
        category = guild.get_channel(int(category_id))
        if category is not None:
            await category.delete(reason="Player section removed")

    return record
