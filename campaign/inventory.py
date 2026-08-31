from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import discord

EXPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "exports"

_CHANNEL_TYPE_LABELS: dict[discord.ChannelType, str] = {
    discord.ChannelType.text: "text",
    discord.ChannelType.voice: "voice",
    discord.ChannelType.forum: "forum",
    discord.ChannelType.news: "announcement",
    discord.ChannelType.stage_voice: "stage",
    discord.ChannelType.category: "category",
}


@dataclass(frozen=True)
class ChannelRow:
    category: str
    category_id: int | None
    name: str
    channel_id: int
    kind: str
    position: int


def channel_kind(channel: discord.abc.GuildChannel) -> str:
    if isinstance(channel, discord.ForumChannel):
        return "forum"
    label = _CHANNEL_TYPE_LABELS.get(channel.type)
    return label or str(channel.type).replace("ChannelType.", "")


def collect_guild_channels(guild: discord.Guild) -> list[ChannelRow]:
    rows: list[ChannelRow] = []
    for channel in guild.channels:
        if (
            isinstance(channel, discord.CategoryChannel)
            or channel.type == discord.ChannelType.category
        ):
            continue
        category = channel.category
        rows.append(
            ChannelRow(
                category=category.name if category is not None else "",
                category_id=category.id if category is not None else None,
                name=channel.name,
                channel_id=channel.id,
                kind=channel_kind(channel),
                position=channel.position,
            )
        )

    category_order = {category.id: category.position for category in guild.categories}
    rows.sort(
        key=lambda row: (
            category_order.get(row.category_id, 10_000) if row.category_id else 10_000,
            row.position,
            row.name.casefold(),
        )
    )
    return rows


def format_channel_list(
    guild: discord.Guild, rows: list[ChannelRow] | None = None
) -> str:
    if rows is None:
        rows = collect_guild_channels(guild)
    grouped: dict[str, list[ChannelRow]] = defaultdict(list)
    for row in rows:
        grouped[row.category or "(no category)"].append(row)

    lines = [
        f"# {guild.name}",
        f"guild_id: {guild.id}",
        f"channels: {len(rows)}",
        "",
    ]
    forums = [row for row in rows if row.kind == "forum"]
    lines.append(f"## Forums ({len(forums)})")
    if forums:
        for row in forums:
            category = row.category or "(no category)"
            lines.append(f"- {row.name}  [{category}]  id={row.channel_id}")
    else:
        lines.append("- none")
    lines.append("")

    seen: set[str] = set()
    for row in rows:
        header = row.category or "(no category)"
        if header in seen:
            continue
        seen.add(header)
        lines.append(f"## {header}")
        for item in grouped[header]:
            lines.append(f"- {item.kind:13} {item.name}  id={item.channel_id}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def channel_list_as_json(
    guild: discord.Guild, rows: list[ChannelRow] | None = None
) -> list[dict]:
    if rows is None:
        rows = collect_guild_channels(guild)
    return [
        {
            "category": row.category,
            "category_id": row.category_id,
            "channel": row.name,
            "channel_id": row.channel_id,
            "type": row.kind,
        }
        for row in rows
    ]


def write_channel_export(guild: discord.Guild) -> Path:
    rows = collect_guild_channels(guild)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPORT_DIR / f"{guild.id}-channels.txt"
    path.write_text(format_channel_list(guild, rows), encoding="utf-8")
    json_path = EXPORT_DIR / f"{guild.id}-channels.json"
    json_path.write_text(
        json.dumps(channel_list_as_json(guild, rows), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return path
