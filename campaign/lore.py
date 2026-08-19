from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import discord

import config as app_config
from config import (
    CAMPAIGN_CACHE_TTL_SECONDS,
    CAMPAIGN_MESSAGES_PER_THREAD,
)

logger = logging.getLogger(__name__)

_CHANNEL_MENTION = re.compile(r"<#(\d+)>")
_LEADING_DECORATION = re.compile(r"^[\W_\d]+", re.UNICODE)
_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "je",
        "tu",
        "il",
        "elle",
        "on",
        "nous",
        "vous",
        "le",
        "la",
        "les",
        "un",
        "une",
        "des",
        "du",
        "de",
        "d",
        "au",
        "aux",
        "et",
        "ou",
        "a",
        "à",
        "en",
        "dans",
        "sur",
        "pour",
        "par",
        "avec",
        "the",
        "and",
        "for",
        "with",
        "from",
        "info",
        "show",
        "liste",
        "list",
    }
)


@dataclass(frozen=True)
class CampaignEntry:
    section: str
    title: str
    body: str
    jump_url: str
    channel_id: int
    search_text: str

    @property
    def link(self) -> str:
        return markdown_channel_link(label=self.title, url=self.jump_url)


_cache_by_guild: dict[int, tuple[float, list[CampaignEntry]]] = {}

# Leading emoji (e.g. "🗡️ Zentharim", "⚖️Tyr") stay outside the markdown link
# so Discord reliably renders a clickable name instead of raw syntax.
_LEADING_EMOJI = re.compile(
    r"^(?P<prefix>(?:[\U0001F300-\U0001FAFF]|[\u2600-\u27BF]|[\uFE0F]|[\u200D]|\s)+)"
    r"(?P<label>\S.*)$",
    re.UNICODE,
)


def markdown_channel_link(*, label: str, url: str) -> str:
    """Build a Discord markdown link; keep emoji/prefix outside the [label](url)."""
    cleaned = label.replace("\\", "").replace("\n", " ").strip()
    prefix = ""
    link_label = cleaned

    match = _LEADING_EMOJI.match(cleaned)
    if match and match.group("label").strip():
        prefix = match.group("prefix").strip()
        link_label = match.group("label").strip()

    safe_label = link_label.replace("[", "(").replace("]", ")").strip()
    if not safe_label:
        safe_label = cleaned.replace("[", "(").replace("]", ")").strip() or "thread"
        prefix = ""

    linked = f"[{safe_label}]({url})"
    return f"{prefix} {linked}".strip() if prefix else linked


def channel_jump_url(*, guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def _section_label(forum_name: str) -> str:
    cleaned = _LEADING_DECORATION.sub("", forum_name).strip()
    return cleaned or forum_name


def _message_text(message: discord.Message) -> str:
    parts: list[str] = []
    if message.content and message.content.strip():
        parts.append(message.content.strip())
    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            name = field.name or ""
            value = field.value or ""
            if name or value:
                parts.append(f"{name}: {value}".strip(": "))
    for attachment in message.attachments:
        parts.append(attachment.url)
    return "\n".join(parts).strip()


def _linkify_channel_mentions(
    text: str,
    *,
    guild_id: int,
    name_by_id: dict[int, str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        channel_id = int(match.group(1))
        label = name_by_id.get(channel_id)
        if not label:
            # Unknown ids stay as plain text id rather than "inconnu" mentions.
            return f"`#{channel_id}`"
        return markdown_channel_link(
            label=label,
            url=channel_jump_url(guild_id=guild_id, channel_id=channel_id),
        )

    return _CHANNEL_MENTION.sub(replace, text)


def find_campaign_category(guild: discord.Guild) -> discord.CategoryChannel | None:
    category_id = app_config.CAMPAIGN_CATEGORY_ID
    if category_id is not None:
        category = guild.get_channel(category_id)
        if isinstance(category, discord.CategoryChannel):
            return category

    needle = app_config.CAMPAIGN_CATEGORY_NAME.casefold()
    for category in guild.categories:
        if needle in category.name.casefold():
            return category
    return None


async def _iter_forum_threads(forum: discord.ForumChannel) -> list[discord.Thread]:
    threads = list(forum.threads)
    seen = {thread.id for thread in threads}
    try:
        async for thread in forum.archived_threads(limit=100):
            if thread.id not in seen:
                threads.append(thread)
                seen.add(thread.id)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("Could not load archived threads for %s: %s", forum.name, exc)
    return threads


async def _fetch_thread_body(thread: discord.Thread) -> str:
    chunks: list[str] = []
    try:
        async for message in thread.history(
            limit=CAMPAIGN_MESSAGES_PER_THREAD,
            oldest_first=True,
        ):
            text = _message_text(message)
            if text:
                chunks.append(text)
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning("Could not read thread %s: %s", thread.name, exc)
        return ""
    return "\n\n".join(chunks).strip()


async def fetch_campaign_entries(
    guild: discord.Guild,
    *,
    force_refresh: bool = False,
) -> list[CampaignEntry]:
    cached = _cache_by_guild.get(guild.id)
    now = time.monotonic()
    if (
        not force_refresh
        and cached is not None
        and now - cached[0] < CAMPAIGN_CACHE_TTL_SECONDS
    ):
        return cached[1]

    category = find_campaign_category(guild)
    if category is None:
        _cache_by_guild[guild.id] = (now, [])
        return []

    forums = [
        channel
        for channel in category.channels
        if isinstance(channel, discord.ForumChannel)
    ]
    forums.sort(key=lambda forum: forum.position)

    forum_threads: list[tuple[str, discord.Thread]] = []
    name_by_id: dict[int, str] = {}
    for forum in forums:
        name_by_id[forum.id] = forum.name
        section = _section_label(forum.name)
        for thread in await _iter_forum_threads(forum):
            name_by_id[thread.id] = thread.name
            forum_threads.append((section, thread))

    entries: list[CampaignEntry] = []
    for section, thread in forum_threads:
        raw_body = await _fetch_thread_body(thread)
        body = _linkify_channel_mentions(
            raw_body,
            guild_id=guild.id,
            name_by_id=name_by_id,
        )
        search_text = f"{section}\n{thread.name}\n{raw_body}\n{body}"
        entries.append(
            CampaignEntry(
                section=section,
                title=thread.name,
                body=body,
                jump_url=thread.jump_url,
                channel_id=thread.id,
                search_text=search_text,
            )
        )

    _cache_by_guild[guild.id] = (now, entries)
    return entries


def extract_query_terms(query: str) -> list[str]:
    tokens = _TOKEN.findall(query.casefold())
    return [token for token in tokens if len(token) >= 3 and token not in _STOPWORDS]


def filter_campaign_entries(
    entries: list[CampaignEntry],
    query: str,
) -> list[CampaignEntry]:
    terms = extract_query_terms(query)
    if not terms:
        return []

    matched: list[CampaignEntry] = []
    for entry in entries:
        haystack = entry.search_text.casefold()
        if any(term in haystack for term in terms):
            matched.append(entry)
    return matched


def format_campaign_index(entries: list[CampaignEntry]) -> str:
    if not entries:
        return "No campaign forum entries found."

    by_section: dict[str, list[CampaignEntry]] = {}
    for entry in entries:
        by_section.setdefault(entry.section, []).append(entry)

    lines = ["**Campaign — index**"]
    for section, section_entries in by_section.items():
        lines.append(f"\n**{section}** ({len(section_entries)})")
        for entry in section_entries:
            lines.append(f"• {entry.link}")
    return "\n".join(lines)


def format_campaign_entry(entry: CampaignEntry) -> str:
    body = entry.body.strip() if entry.body.strip() else "_(no text in this thread)_"
    return f"**{entry.section}** — {entry.link}\n\n{body}"


def clear_campaign_cache(guild_id: int | None = None) -> None:
    if guild_id is None:
        _cache_by_guild.clear()
    else:
        _cache_by_guild.pop(guild_id, None)
