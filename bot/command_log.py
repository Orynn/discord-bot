from __future__ import annotations

import logging

import discord
from discord.errors import Forbidden, HTTPException
from discord.ext.commands.context import Context

from bot.rate_limits import retry_on_rate_limit

LOG_CHANNEL_NAME = "📜arkann-log"

logger = logging.getLogger(__name__)
_missing_log_channel_guilds: set[int] = set()
_denied_log_channel_guilds: set[int] = set()


def find_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)


def _format_option_value(value: object) -> str:
    if isinstance(value, (discord.Member, discord.User)):
        return value.mention
    if isinstance(value, discord.Attachment):
        return f"[{value.filename}]"
    if isinstance(value, discord.Role):
        return value.mention
    text = str(value).strip()
    if not text:
        return '""'
    if len(text) > 120:
        return text[:117] + "…"
    return text


def format_command_invocation(ctx: Context) -> str:
    command = ctx.command
    if command is None:
        return ""

    if ctx.interaction is not None:
        parts = [f"/{command.qualified_name}"]
        for key, value in ctx.kwargs.items():
            if value is None:
                continue
            parts.append(f"{key}: {_format_option_value(value)}")
        return " ".join(parts)

    content = (getattr(ctx.message, "content", None) or "").strip()
    if content:
        return content
    return f";{command.qualified_name}"


def inspect_log_channel(guild: discord.Guild) -> None:
    channel = find_log_channel(guild)
    if channel is None:
        logger.warning(
            "Command log channel %r not visible in %s (%s). "
            "Arkann sees %s text channel(s). "
            "Check that the bot can view %r.",
            LOG_CHANNEL_NAME,
            guild.name,
            guild.id,
            len(guild.text_channels),
            LOG_CHANNEL_NAME,
        )
        return

    me = guild.me
    if me is None:
        return
    perms = channel.permissions_for(me)
    if not perms.view_channel or not perms.send_messages:
        logger.warning(
            "Cannot write command logs to %s in %s (%s): view=%s send=%s.",
            channel.name,
            guild.name,
            guild.id,
            perms.view_channel,
            perms.send_messages,
        )


async def _post_log(
    log_channel: discord.TextChannel,
    message: str,
    *,
    guild: discord.Guild,
) -> None:
    try:
        await retry_on_rate_limit(lambda: log_channel.send(message))
    except Forbidden:
        if guild.id not in _denied_log_channel_guilds:
            _denied_log_channel_guilds.add(guild.id)
            logger.warning(
                "Forbidden to send command logs to %s in %s (%s).",
                log_channel.name,
                guild.name,
                guild.id,
            )
    except HTTPException as exc:
        logger.warning(
            "Could not send command log to %s in %s: %s",
            log_channel.name,
            guild.name,
            exc,
        )


async def log_command(ctx: Context) -> None:
    if ctx.guild is None or ctx.command is None:
        return

    guild_id = ctx.guild.id
    log_channel = find_log_channel(ctx.guild)
    if log_channel is None:
        if guild_id not in _missing_log_channel_guilds:
            _missing_log_channel_guilds.add(guild_id)
            inspect_log_channel(ctx.guild)
        return

    channel_ref = (
        ctx.channel.mention
        if isinstance(ctx.channel, discord.abc.GuildChannel)
        else "unknown"
    )
    invocation = format_command_invocation(ctx)
    message = (
        f"**{ctx.author.display_name}** (`{ctx.author.id}`) "
        f"used `{ctx.command.qualified_name}` in {channel_ref}\n"
        f"`{invocation}`"
    )
    await _post_log(log_channel, message, guild=ctx.guild)


async def log_app_command(
    interaction: discord.Interaction,
    command: discord.app_commands.Command | discord.app_commands.ContextMenu,
) -> None:
    if interaction.guild is None:
        return
    if getattr(command, "__commands_is_hybrid_app_command__", False):
        return

    guild_id = interaction.guild.id
    log_channel = find_log_channel(interaction.guild)
    if log_channel is None:
        if guild_id not in _missing_log_channel_guilds:
            _missing_log_channel_guilds.add(guild_id)
            inspect_log_channel(interaction.guild)
        return

    channel = interaction.channel
    channel_ref = (
        channel.mention if isinstance(channel, discord.abc.GuildChannel) else "unknown"
    )
    qualified = getattr(command, "qualified_name", command.name)
    parts = [f"/{qualified}"]
    namespace = interaction.namespace
    if namespace is not None:
        for key, value in namespace:
            if value is None:
                continue
            parts.append(f"{key}: {_format_option_value(value)}")
    invocation = " ".join(parts)
    user = interaction.user
    message = (
        f"**{user.display_name}** (`{user.id}`) "
        f"used `{qualified}` in {channel_ref}\n"
        f"`{invocation}`"
    )
    await _post_log(log_channel, message, guild=interaction.guild)
