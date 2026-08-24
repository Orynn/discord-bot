from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from config import (
    IMAGE_COOLDOWN_SECONDS,
    IMAGE_HISTORY_LIMIT,
    PLAYER_CHANNEL_OOC,
    PLAYER_CHANNEL_RP,
    PREFIX,
)
from image.generate import (
    ImageGenerationError,
    ImagePromptError,
    build_prompt,
    extract_scene_line,
    generate_image,
    public_caption,
)
from sheets.context import resolve_guild_id
from sheets.storage import get_character_name, get_sheet

logger = logging.getLogger(__name__)


def _character_name(ctx: Context) -> str | None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        return None
    sheet = get_sheet(user_id=ctx.author.id, guild_id=guild_id)
    if sheet is not None and sheet.name:
        return sheet.name
    stored = get_character_name(user_id=ctx.author.id, guild_id=guild_id)
    return stored or None


def _is_generic_channel_name(name: str) -> bool:
    folded = name.casefold()
    markers = [PLAYER_CHANNEL_RP, PLAYER_CHANNEL_OOC, "roleplay", "blabla", "ooc"]
    return any(marker and marker.casefold() in folded for marker in markers)


def scene_place(channel: discord.abc.Messageable) -> str | None:
    name = (getattr(channel, "name", None) or "").strip()
    if name and not _is_generic_channel_name(name):
        return name
    topic = (getattr(channel, "topic", None) or "").strip()
    return topic or None


def _message_line(message: discord.Message, *, skip_id: int | None) -> str | None:
    if skip_id is not None and message.id == skip_id:
        return None
    author = getattr(message.author, "display_name", None)
    is_bot = bool(getattr(message.author, "bot", False))
    return extract_scene_line(
        content=message.clean_content,
        prefix=PREFIX,
        is_bot=is_bot,
        author=author,
        has_attachments=bool(message.attachments),
    )


async def gather_scene_lines(ctx: Context, *, limit: int | None = None) -> list[str]:
    history = getattr(ctx.channel, "history", None)
    if history is None:
        return []
    cap = IMAGE_HISTORY_LIMIT if limit is None else limit
    lines: list[str] = []
    skip_id = getattr(getattr(ctx, "message", None), "id", None)
    try:
        async for message in history(limit=cap):
            line = _message_line(message, skip_id=skip_id)
            if line is None:
                continue
            lines.append(line)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.info("Could not read scene history in %s: %s", ctx.channel, exc)
        return []
    lines.reverse()
    return lines


def setup_image(bot: Bot) -> None:
    @bot.hybrid_command(
        name="image",
        aliases=["dessine", "draw", "img"],
        help="Illustrate this channel's roleplay, optionally focused by a prompt.",
    )
    @app_commands.describe(
        prompt="Optional focus. The bot still reads this channel's RP."
    )
    @commands.cooldown(1, max(1, IMAGE_COOLDOWN_SECONDS), commands.BucketType.user)
    async def image_command(ctx: Context, *, prompt: str = "") -> None:
        user_prompt = (prompt or "").strip()
        place = scene_place(ctx.channel)
        character = _character_name(ctx)

        if ctx.interaction is not None and not ctx.interaction.response.is_done():
            await ctx.defer()

        try:
            async with ctx.typing():
                scene_lines = await gather_scene_lines(ctx)
                try:
                    full_prompt = build_prompt(
                        user_prompt=user_prompt,
                        place=place,
                        character=character,
                        scene_lines=scene_lines,
                    )
                except ImagePromptError as exc:
                    await command_reply(
                        ctx, str(exc), linkify=False, definition_menu=False
                    )
                    await delete_command(ctx)
                    return
                image = await generate_image(full_prompt)
        except ImageGenerationError as exc:
            await command_reply(ctx, str(exc), linkify=False, definition_menu=False)
            await delete_command(ctx)
            return

        caption = public_caption(
            user_prompt=user_prompt,
            place=place,
            from_scene=bool(scene_lines),
        )
        await send_message(
            ctx,
            content=f"*{caption}*",
            file=discord.File(io.BytesIO(image.data), filename=image.filename),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)
