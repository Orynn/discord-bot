import copy
import re

import discord

from srd.glossary import GlossaryEntry, find_mentions, is_loaded, iter_mention_spans

_PROTECTED = re.compile(
    r"```[\s\S]*?```"
    r"|`[^`]+`"
    r"|\[[^\]]+\]\([^)]+\)"
)


def markdown_link(label: str, url: str) -> str:
    """Masked Discord link — encode underscores in the URL so markdown does not break."""
    safe_url = url.replace("_", "%5F")
    return f"[{label}]({safe_url})"


def _linkify_plain(text: str) -> str:
    if not text or not is_loaded():
        return text

    spans = iter_mention_spans(text)
    if not spans:
        return text

    result = text
    for start, end, original, entry in reversed(spans):
        result = f"{result[:start]}{markdown_link(original, entry.url)}{result[end:]}"
    return result


def linkify_text(text: str) -> str:
    if not text:
        return text

    parts: list[str] = []
    last = 0
    for match in _PROTECTED.finditer(text):
        parts.append(_linkify_plain(text[last : match.start()]))
        parts.append(match.group(0))
        last = match.end()
    parts.append(_linkify_plain(text[last:]))
    return "".join(parts)


def _collect_embed_text(embed: discord.Embed) -> str:
    chunks = [embed.title or "", embed.description or ""]
    for field in embed.fields:
        chunks.extend([field.name, field.value])
    if embed.footer.text:
        chunks.append(embed.footer.text)
    return "\n".join(chunk for chunk in chunks if chunk)


def linkify_embed(embed: discord.Embed) -> discord.Embed:
    if not is_loaded():
        return embed

    linked = copy.copy(embed)
    if linked.description:
        linked.description = linkify_text(linked.description)

    for index, field in enumerate(linked.fields):
        linked.set_field_at(
            index=index,
            name=field.name,
            value=linkify_text(field.value),
            inline=field.inline,
        )
    return linked


def linkify_embeds(embeds: list[discord.Embed]) -> list[discord.Embed]:
    return [linkify_embed(embed) for embed in embeds]


def mentioned_entries(
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    embeds: list[discord.Embed] | None = None,
) -> list[GlossaryEntry]:
    chunks: list[str] = []
    if content:
        chunks.append(content)
    if embed:
        chunks.append(_collect_embed_text(embed))
    if embeds:
        for item in embeds:
            chunks.append(_collect_embed_text(item))
    return find_mentions(text="\n".join(chunks))
