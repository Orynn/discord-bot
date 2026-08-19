from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

import discord

from campaign.forums import (
    CampaignForumError,
    iter_forum_threads,
    list_campaign_forums,
)
from campaign.wiki import ProgressCallback

_HISTORY_LIMIT = 50
_COPY_DELAY = 0.35
_EDIT_DELAY = 0.2
_MOVE_NOTE = re.compile(
    r"^_(?:Déplacé vers|Recatégorisé vers|Post déjà présent)\b",
    re.IGNORECASE,
)
_THREAD_JUMP = re.compile(
    r"https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)(?:/\d+)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MoveResult:
    title: str
    source: discord.ForumChannel
    target: discord.ForumChannel
    old_thread: discord.Thread
    thread: discord.Thread
    created: bool
    relinked: int


def is_move_note(content: str | None) -> bool:
    if not content:
        return False
    return _MOVE_NOTE.search(content.strip()) is not None


def rewrite_moved_links(
    text: str,
    *,
    old_thread_id: int,
    new_url: str,
    title: str,
    old_section: str,
    new_section: str,
) -> str:
    def replace_jump(match: re.Match[str]) -> str:
        if int(match.group(2)) != old_thread_id:
            return match.group(0)
        return new_url

    updated = _THREAD_JUMP.sub(replace_jump, text)
    if old_section and new_section and old_section != new_section:
        updated = updated.replace(
            f"{old_section} — [{title}]",
            f"{new_section} — [{title}]",
        )
    return updated


def forum_for_thread(
    forums: list[discord.ForumChannel],
    thread: discord.Thread,
) -> discord.ForumChannel | None:
    parent = getattr(thread, "parent", None)
    parent_id = getattr(parent, "id", None) or getattr(thread, "parent_id", None)
    if parent_id is None:
        return None
    for forum in forums:
        if forum.id == parent_id:
            return forum
    if isinstance(parent, discord.ForumChannel):
        return parent
    return None


async def _emit(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def _unarchive(thread: discord.Thread) -> None:
    if not thread.archived:
        return
    await thread.edit(archived=False, locked=False)


async def _archive_with_note(thread: discord.Thread, note: str) -> None:
    try:
        await _unarchive(thread)
        await thread.send(note)
        await thread.edit(archived=True, locked=True)
    except discord.HTTPException:
        return


async def _thread_files(message: discord.Message) -> list[discord.File]:
    files: list[discord.File] = []
    for attachment in message.attachments[:10]:
        try:
            files.append(await attachment.to_file())
        except (OSError, discord.HTTPException, discord.NotFound):
            continue
    return files


def _send_kwargs(content: str, files: list[discord.File]) -> dict:
    kwargs: dict = {}
    if content.strip():
        kwargs["content"] = content
    if len(files) == 1:
        kwargs["file"] = files[0]
    elif files:
        kwargs["files"] = files
    return kwargs


async def _collect_messages(
    thread: discord.Thread,
    *,
    skip_message_ids: set[int],
) -> list[discord.Message]:
    await _unarchive(thread)
    messages: list[discord.Message] = []
    try:
        async for message in thread.history(limit=_HISTORY_LIMIT, oldest_first=True):
            if getattr(message, "id", None) in skip_message_ids:
                continue
            if is_move_note(message.content):
                continue
            if not (message.content or "").strip() and not message.attachments:
                continue
            messages.append(message)
    except (discord.Forbidden, discord.HTTPException) as exc:
        raise CampaignForumError(f"Impossible de lire le post **{thread.name}** : {exc}") from exc
    if not messages:
        raise CampaignForumError(f"Le post **{thread.name}** n'a aucun contenu à déplacer.")
    return messages


async def _copy_messages(
    *,
    target: discord.ForumChannel,
    name: str,
    messages: list[discord.Message],
) -> discord.Thread:
    starter = messages[0]
    files = await _thread_files(starter)
    kwargs = _send_kwargs(starter.content or "", files)
    if not kwargs:
        kwargs["content"] = f"**{name}**"
    created = await target.create_thread(name=name[:100], **kwargs)
    thread = created.thread
    for message in messages[1:]:
        copied = await _thread_files(message)
        send_kwargs = _send_kwargs(message.content or "", copied)
        if not send_kwargs:
            continue
        try:
            await thread.send(**send_kwargs)
        except discord.HTTPException:
            break
        await asyncio.sleep(_COPY_DELAY)
    return thread


async def _relink_messages(
    forums: list[discord.ForumChannel],
    *,
    old_thread_id: int,
    new_url: str,
    title: str,
    old_section: str,
    new_section: str,
    skip_ids: set[int],
) -> int:
    edited = 0
    for forum in forums:
        for thread in await iter_forum_threads(forum):
            if thread.id in skip_ids:
                continue
            try:
                async for message in thread.history(limit=_HISTORY_LIMIT, oldest_first=True):
                    content = message.content or ""
                    if not content:
                        continue
                    updated = rewrite_moved_links(
                        content,
                        old_thread_id=old_thread_id,
                        new_url=new_url,
                        title=title,
                        old_section=old_section,
                        new_section=new_section,
                    )
                    if updated == content:
                        continue
                    try:
                        await message.edit(content=updated)
                    except (discord.Forbidden, discord.HTTPException):
                        continue
                    edited += 1
                    await asyncio.sleep(_EDIT_DELAY)
            except (discord.Forbidden, discord.HTTPException):
                continue
    return edited


async def _existing_in_forum(forum: discord.ForumChannel, title: str) -> discord.Thread | None:
    needle = title.casefold().strip()
    for thread in await iter_forum_threads(forum):
        if thread.name.casefold() == needle:
            return thread
    return None


async def move_campaign_post(
    *,
    guild: discord.Guild,
    thread: discord.Thread,
    target: discord.ForumChannel,
    on_progress: ProgressCallback | None = None,
    skip_message_ids: set[int] | None = None,
) -> MoveResult:
    forums = list_campaign_forums(guild)
    source = forum_for_thread(forums, thread)
    if source is None:
        raise CampaignForumError("Ce post n'est pas dans un forum CAMPAIGN.")
    if source.id == target.id:
        raise CampaignForumError(f"**{thread.name}** est déjà dans {target.mention}.")

    existing = await _existing_in_forum(target, thread.name)
    created = False
    if existing is not None and existing.id != thread.id:
        relocated = existing
        await _emit(on_progress, f"📦 Post déjà dans {target.mention} — mise à jour des liens…")
    else:
        await _emit(on_progress, f"📦 Copie de **{thread.name}** vers {target.mention}…")
        messages = await _collect_messages(
            thread,
            skip_message_ids=skip_message_ids or set(),
        )
        relocated = await _copy_messages(target=target, name=thread.name, messages=messages)
        created = True

    await _emit(on_progress, "🔗 Mise à jour des connexions…")
    relinked = await _relink_messages(
        forums,
        old_thread_id=thread.id,
        new_url=relocated.jump_url,
        title=thread.name,
        old_section=source.name,
        new_section=target.name,
        skip_ids={thread.id},
    )
    if created:
        note = f"_Déplacé vers {relocated.jump_url} ({target.mention})._"
    else:
        note = f"_Post déjà présent dans {target.mention} : {relocated.jump_url}_"
    await _archive_with_note(thread, note)
    return MoveResult(
        title=thread.name,
        source=source,
        target=target,
        old_thread=thread,
        thread=relocated,
        created=created,
        relinked=relinked,
    )
