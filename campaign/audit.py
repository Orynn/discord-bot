from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from typing import Literal

import discord

from campaign.forums import (
    CampaignForumError,
    ensure_campaign_forum,
    ensure_default_campaign_forums,
    iter_forum_threads,
    list_campaign_forums,
    normalize_section_key,
)
from campaign.moving import move_campaign_post
from campaign.wiki import (
    ProgressCallback,
    WikiError,
    WikiNotFoundError,
    WikiPage,
    fetch_wiki_page,
)

AuditStatus = Literal["ok", "misplaced", "missing_wiki"]

_WIKI_DELAY = 0.3


@dataclass(frozen=True)
class AuditItem:
    title: str
    jump_url: str
    current_section: str
    expected_section: str | None
    status: AuditStatus
    moved: bool = False


def classify_placement(*, current_section: str, expected_section: str | None) -> AuditStatus:
    if expected_section is None:
        return "missing_wiki"
    if normalize_section_key(current_section) == normalize_section_key(expected_section):
        return "ok"
    return "misplaced"


def format_audit_report(items: list[AuditItem]) -> str:
    misplaced = [item for item in items if item.status == "misplaced"]
    missing = [item for item in items if item.status == "missing_wiki"]
    ok = [item for item in items if item.status == "ok"]
    moved = [item for item in items if item.moved]
    lines = [
        f"posts: {len(items)}",
        f"ok: {len(ok)}",
        f"misplaced: {len(misplaced)}",
        f"missing_wiki: {len(missing)}",
        f"moved: {len(moved)}",
        "",
    ]
    if misplaced:
        lines.append("## Mal classés")
        for item in misplaced:
            dest = item.expected_section or "?"
            flag = " → déplacé" if item.moved else ""
            lines.append(
                f"- {item.title}  [{item.current_section} → {dest}]{flag}  {item.jump_url}"
            )
        lines.append("")
    if missing:
        lines.append("## Pas de page wiki")
        for item in missing:
            lines.append(f"- {item.title}  [{item.current_section}]  {item.jump_url}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def audit_report_file(items: list[AuditItem], *, guild_id: int) -> discord.File:
    payload = format_audit_report(items).encode("utf-8")
    return discord.File(io.BytesIO(payload), filename=f"{guild_id}-campaign-audit.txt")


async def _emit(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def audit_campaign_posts(
    guild: discord.Guild,
    *,
    fix: bool = False,
    on_progress: ProgressCallback | None = None,
) -> list[AuditItem]:
    await ensure_default_campaign_forums(guild)
    forums = list_campaign_forums(guild)
    items: list[AuditItem] = []
    listings: list[tuple[discord.ForumChannel, discord.Thread]] = []
    for forum in forums:
        for thread in await iter_forum_threads(forum):
            if thread.archived and getattr(thread, "locked", False):
                continue
            listings.append((forum, thread))
    total = len(listings)

    for index, (forum, thread) in enumerate(listings, start=1):
        current = normalize_section_key(forum.name)
        await _emit(on_progress, f"🔎 Audit… **{index}/{total}** (`{thread.name}`)")
        expected: str | None = None
        page: WikiPage | None = None
        try:
            page = await fetch_wiki_page(thread.name, suggest=False)
            expected = page.section
        except WikiNotFoundError:
            expected = None
        except WikiError:
            expected = None
        status = classify_placement(current_section=current, expected_section=expected)
        moved = False
        jump = thread.jump_url
        if fix and status == "misplaced" and page is not None and expected is not None:
            try:
                target = await ensure_campaign_forum(guild, expected)
                relocated = await move_campaign_post(
                    guild=guild,
                    thread=thread,
                    target=target,
                    on_progress=on_progress,
                )
            except (CampaignForumError, discord.Forbidden, discord.HTTPException):
                relocated = None
            if relocated is not None:
                moved = True
                jump = relocated.thread.jump_url
        items.append(
            AuditItem(
                title=thread.name,
                jump_url=jump,
                current_section=current,
                expected_section=expected,
                status=status,
                moved=moved,
            )
        )
        await asyncio.sleep(_WIKI_DELAY)
    return items
