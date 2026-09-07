import logging
import re
from typing import FrozenSet, Literal

import discord
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.help_commands import tokens_request_help
from bot.help_text import command_help
from bot.messaging import send_message
from bot.names import get_known_character_names
from bot.speech import parenthetical_only_narration
from config import PREFIX
from sheets.context import resolve_guild_id

logger = logging.getLogger(__name__)

_ENDING_PUNCTUATION: FrozenSet[str] = frozenset(".!?,;:")
_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_MAX_DESC_IMAGES = 10
_TOPIC_LIMIT = 1024
TopicClearStatus = Literal["cleared", "empty", "forbidden", "unsupported", "failed"]
TopicWriteStatus = Literal[
    "updated", "unchanged", "empty", "forbidden", "unsupported", "failed"
]
_TOPIC_ERROR_REPLIES: dict[str, str] = {
    "forbidden": "Il me faut la permission de gérer les salons.",
    "unsupported": "Je ne peux pas changer la description ici.",
    "failed": "Je n’ai pas pu changer la description du salon.",
}


def format_channel_topic(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    if len(cleaned) <= _TOPIC_LIMIT:
        return cleaned
    return cleaned[: _TOPIC_LIMIT - 1].rstrip() + "…"


async def clear_channel_topic(channel: discord.abc.Messageable) -> TopicClearStatus:
    if not hasattr(channel, "topic"):
        return "unsupported"
    edit = getattr(channel, "edit", None)
    if not callable(edit):
        return "unsupported"
    current = (getattr(channel, "topic", None) or "").strip()
    if not current:
        return "empty"
    try:
        await edit(topic="")
    except TypeError:
        return "unsupported"
    except discord.Forbidden:
        return "forbidden"
    except discord.HTTPException as exc:
        logger.info("Could not clear channel topic for %s: %s", channel, exc)
        return "failed"
    return "cleared"


async def clear_scene_channel_topic(ctx: Context) -> None:
    status = await clear_channel_topic(ctx.channel)
    error = _TOPIC_ERROR_REPLIES.get(status)
    if error:
        await command_reply(ctx, error)
    await delete_command(ctx)


async def set_channel_topic(
    channel: discord.abc.Messageable, text: str
) -> TopicWriteStatus:
    if not hasattr(channel, "topic"):
        return "unsupported"
    edit = getattr(channel, "edit", None)
    if not callable(edit):
        return "unsupported"
    topic = format_channel_topic(text)
    if not topic:
        return "empty"
    current = (getattr(channel, "topic", None) or "").strip()
    if current == topic:
        return "unchanged"
    try:
        await edit(topic=topic)
    except TypeError:
        return "unsupported"
    except discord.Forbidden:
        return "forbidden"
    except discord.HTTPException as exc:
        logger.info("Could not update channel topic for %s: %s", channel, exc)
        return "failed"
    return "updated"


async def set_scene_channel_topic(ctx: Context, text: str) -> None:
    cleaned = text.strip()
    if not cleaned:
        await command_reply(ctx, f"Usage : `{PREFIX}desc set <texte>`")
        await delete_command(ctx)
        return
    status = await set_channel_topic(ctx.channel, cleaned)
    error = _TOPIC_ERROR_REPLIES.get(status)
    if error:
        await command_reply(ctx, error)
    await delete_command(ctx)


def _is_already_bold(text: str, start: int, end: int) -> bool:
    return (
        start >= 2 and text[start - 2 : start] == "**" and text[end : end + 2] == "**"
    )


def _format_known_names(text: str, *, guild_id: int) -> str:
    known_names = get_known_character_names(guild_id=guild_id)
    if not known_names:
        return text

    candidates: list[tuple[int, int, str]] = []
    for name in known_names:
        pattern = re.compile(rf"(?<![\w*]){re.escape(name)}(?![\w*])", re.IGNORECASE)
        for match in pattern.finditer(text):
            start, end = match.start(), match.end()
            if _is_already_bold(text=text, start=start, end=end):
                continue
            candidates.append((start, end, match.group(0)))

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, original in candidates:
        if any(
            not (end <= occ_start or start >= occ_end)
            for occ_start, occ_end in occupied
        ):
            continue
        selected.append((start, end, original))
        occupied.append((start, end))

    result = text
    for start, end, original in sorted(
        selected, key=lambda item: item[0], reverse=True
    ):
        result = f"{result[:start]}**{original}**{result[end:]}"
    return result


def _format_description(text: str, *, guild_id: int) -> str:
    text = _format_known_names(text=text.rstrip(), guild_id=guild_id)
    if not text:
        return ""
    if text[-1] not in _ENDING_PUNCTUATION:
        text = f"{text}."
    return f"*{text}*"


def is_image_attachment(attachment: discord.Attachment) -> bool:
    content = (attachment.content_type or "").split(";", 1)[0].strip().casefold()
    if content.startswith("image/"):
        return True
    name = (attachment.filename or "").casefold()
    return name.endswith(_IMAGE_SUFFIXES)


async def collect_desc_images(
    ctx: Context,
    extra: discord.Attachment | None = None,
) -> list[discord.File]:
    files: list[discord.File] = []
    seen: set[int] = set()
    attachments: list[discord.Attachment] = []
    if extra is not None:
        attachments.append(extra)
    if ctx.message is not None:
        attachments.extend(ctx.message.attachments)
    for attachment in attachments:
        if attachment.id in seen or not is_image_attachment(attachment):
            continue
        seen.add(attachment.id)
        files.append(await attachment.to_file())
        if len(files) >= _MAX_DESC_IMAGES:
            break
    return files


async def send_scene_description(
    ctx: Context,
    text: str,
    extra: discord.Attachment | None = None,
) -> None:
    files = await collect_desc_images(ctx, extra)
    cleaned = text.strip()
    if not cleaned and not files:
        await command_reply(
            ctx,
            f"Usage : `{PREFIX}desc <texte>` — tu peux aussi joindre une image.",
        )
        await delete_command(ctx)
        return

    guild_id = resolve_guild_id(ctx) or 0
    kwargs: dict = {
        "linkify": False,
        "definition_menu": False,
    }
    if len(files) == 1:
        kwargs["file"] = files[0]
    elif files:
        kwargs["files"] = files
    await send_message(
        ctx,
        content=_format_description(cleaned, guild_id=guild_id) or None,
        **kwargs,
    )
    await delete_command(ctx)


async def maybe_send_parenthetical_desc(ctx: Context, text: str) -> bool:
    narration = parenthetical_only_narration(text)
    if narration is None:
        return False
    await send_scene_description(ctx, narration)
    return True


def setup_desc(bot: Bot) -> None:
    @bot.hybrid_group(
        name="desc",
        invoke_without_command=True,
        help=command_help(
            "Narre une scène en italique. La description du salon ne change qu’avec `desc set`.",
            f"`{PREFIX}desc <texte>`",
            f"`{PREFIX}desc set <texte>` — description du salon seulement",
            f"`{PREFIX}desc clear` — efface la description du salon",
        ),
    )
    async def desc_group(
        ctx: Context,
        *,
        text: str = "",
        file: discord.Attachment | None = None,
    ) -> None:
        if tokens_request_help(text.split()):
            await ctx.send_help(ctx.command)
            return
        await send_scene_description(ctx, text, extra=file)

    @desc_group.command(
        name="set",
        aliases=["topic", "update", "sujet"],
        help=command_help(
            "Met à jour la description de ce salon, sans poster de narration.",
            f"`{PREFIX}desc set <texte>`",
        ),
    )
    async def desc_set(ctx: Context, *, text: str = "") -> None:
        if tokens_request_help(text.split()):
            await ctx.send_help(ctx.command)
            return
        await set_scene_channel_topic(ctx, text)

    @desc_group.command(
        name="clear",
        aliases=["reset", "vide", "efface"],
        help=command_help(
            "Efface la description de ce salon.",
            f"`{PREFIX}desc clear`",
        ),
    )
    async def desc_clear(ctx: Context) -> None:
        await clear_scene_channel_topic(ctx)
