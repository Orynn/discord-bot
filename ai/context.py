import logging

import discord
from discord.ext.commands.context import Context

from campaign.lore import CampaignEntry, fetch_campaign_entries, select_campaign_entries

logger = logging.getLogger(__name__)

_LINE_LIMIT = 400
_LORE_ENTRY_LIMIT = 3
_LORE_BODY_LIMIT = 500
_LORE_TOTAL_LIMIT = 1600


def format_history_line(message: discord.Message) -> str | None:
    content = (
        getattr(message, "clean_content", None)
        or getattr(message, "content", None)
        or ""
    ).strip()
    has_files = bool(getattr(message, "attachments", None))
    if not content and not has_files:
        return None
    author = (
        getattr(getattr(message, "author", None), "display_name", None) or "Quelqu’un"
    )
    text = " ".join(content.split()) if content else ""
    if len(text) > _LINE_LIMIT:
        text = text[: _LINE_LIMIT - 1].rstrip() + "…"
    bits = [part for part in (text, "[image]" if has_files else "") if part]
    return f"{author}: {' '.join(bits)}"


async def gather_recent_messages(ctx: Context, *, limit: int) -> list[str]:
    history = getattr(ctx.channel, "history", None)
    if history is None or limit <= 0:
        return []
    skip_id = getattr(getattr(ctx, "message", None), "id", None)
    collected: list[str] = []
    try:
        async for message in history(limit=limit + 1):
            if skip_id is not None and getattr(message, "id", None) == skip_id:
                continue
            line = format_history_line(message)
            if line is None:
                continue
            collected.append(line)
            if len(collected) >= limit:
                break
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.info("Could not read recent messages in %s: %s", ctx.channel, exc)
        return []
    collected.reverse()
    return collected


def lore_query(*chunks: str) -> str:
    return " ".join(part.strip() for part in chunks if part and part.strip())


def format_campaign_lore(entries: list[CampaignEntry]) -> str:
    blocks: list[str] = []
    used = 0
    for entry in entries[:_LORE_ENTRY_LIMIT]:
        body = " ".join((entry.body or "").split())
        if len(body) > _LORE_BODY_LIMIT:
            body = body[: _LORE_BODY_LIMIT - 1].rstrip() + "…"
        heading = f"{entry.section} — {entry.title}".strip(" —")
        block = f"{heading}\n{body}" if body else heading
        extra = 2 if blocks else 0
        if used and used + extra + len(block) > _LORE_TOTAL_LIMIT:
            break
        if not blocks and len(block) > _LORE_TOTAL_LIMIT:
            block = block[: _LORE_TOTAL_LIMIT - 1].rstrip() + "…"
        blocks.append(block)
        used += extra + len(block)
    return "\n\n".join(blocks)


async def gather_campaign_lore(guild: discord.Guild | None, query: str) -> str:
    if guild is None or not query.strip():
        return ""
    try:
        entries = await fetch_campaign_entries(guild)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.info("Could not read CAMPAIGN lore in %s: %s", guild, exc)
        return ""
    selected = select_campaign_entries(entries, query, limit=_LORE_ENTRY_LIMIT)
    return format_campaign_lore(selected)
