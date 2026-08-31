from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace

import discord

from campaign.forums import (
    ensure_campaign_forum,
    ensure_default_campaign_forums,
    iter_forum_threads,
    locate_campaign_thread,
    list_campaign_forums,
)
from campaign.wiki import (
    MAX_FOLLOWUPS,
    MAX_IMPORT_PAGES,
    ProgressCallback,
    WikiError,
    WikiNotFoundError,
    WikiPage,
    connections_block,
    download_thumbnail,
    fetch_wiki_cluster,
    fetch_wiki_page,
    rewrite_imported_links,
)

IMPORT_PLACEHOLDER = "_Import des liens…_"
WIKI_CONTINUATION = "suite sur le wiki"
_FILL_DELAY = 0.2
_WIKI_DELAY = 0.3
_guild_locks: dict[int, asyncio.Lock] = {}


@dataclass(frozen=True)
class ImportedPost:
    page: WikiPage
    thread: discord.Thread
    forum: discord.ForumChannel
    created: bool
    needs_fill: bool = False


@dataclass(frozen=True)
class WikiImportResult:
    posts: list[ImportedPost]
    truncated: bool
    max_pages: int
    missing_wiki: tuple[str, ...] = ()
    failed_wiki: tuple[str, ...] = ()


@dataclass(frozen=True)
class RepairResult:
    repaired: list[discord.Thread]
    missing_wiki: tuple[str, ...]
    scanned: int


def _rewrite_page(
    page: WikiPage,
    jump_urls: dict[str, str],
    sections: dict[str, str],
    *,
    extra_outgoing: tuple[str, ...] = (),
) -> WikiPage:
    outgoing = tuple(
        title
        for title in dict.fromkeys([*extra_outgoing, *page.outgoing])
        if title.casefold() != page.title.casefold()
    )
    linked = page.with_connections(
        connections_block(
            outgoing=outgoing,
            jump_urls=jump_urls,
            sections=sections,
        )
    )
    return replace(
        linked,
        summary=rewrite_imported_links(linked.summary, jump_urls),
        body=rewrite_imported_links(linked.body, jump_urls),
    )


def has_import_placeholder(content: str | None) -> bool:
    if not content:
        return False
    return "import des liens" in content.casefold()


def has_wiki_continuation(content: str | None) -> bool:
    if not content:
        return False
    return WIKI_CONTINUATION in content.casefold()


def needs_wiki_fill(content: str | None) -> bool:
    return has_import_placeholder(content) or has_wiki_continuation(content)


async def thread_needs_wiki_fill(
    thread: discord.Thread,
    starter: discord.Message | None,
) -> bool:
    if needs_wiki_fill(starter.content if starter else None):
        return True
    for message in await _collect_followups(thread, starter):
        if needs_wiki_fill(message.content):
            return True
    return False


async def resolve_starter(thread: discord.Thread) -> discord.Message | None:
    starter = getattr(thread, "starter_message", None)
    if starter is not None:
        return starter
    try:
        return await thread.fetch_message(thread.id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass
    try:
        async for message in thread.history(limit=1, oldest_first=True):
            return message
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def _unarchive(thread: discord.Thread) -> None:
    if not getattr(thread, "archived", False):
        return
    try:
        await thread.edit(archived=False, locked=False)
    except discord.HTTPException:
        return


def _lock_for(guild_id: int) -> asyncio.Lock:
    lock = _guild_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        _guild_locks[guild_id] = lock
    return lock


def _authored_by_bot(message: discord.Message, thread: discord.Thread) -> bool:
    author = getattr(message, "author", None)
    if author is None:
        return True
    me = getattr(getattr(thread, "guild", None), "me", None)
    if me is not None:
        return getattr(author, "id", None) == getattr(me, "id", None)
    return bool(getattr(author, "bot", False))


async def _collect_followups(
    thread: discord.Thread,
    starter: discord.Message | None,
) -> list[discord.Message]:
    found: list[discord.Message] = []
    try:
        async for message in thread.history(limit=MAX_FOLLOWUPS + 5, oldest_first=True):
            if starter is not None and message.id == starter.id:
                continue
            if not _authored_by_bot(message, thread):
                continue
            found.append(message)
            if len(found) >= MAX_FOLLOWUPS:
                break
    except (discord.Forbidden, discord.HTTPException):
        return found
    return found


async def _has_foreign_followups(
    thread: discord.Thread,
    starter: discord.Message | None,
) -> bool:
    try:
        async for message in thread.history(limit=MAX_FOLLOWUPS + 5, oldest_first=True):
            if starter is not None and message.id == starter.id:
                continue
            if _authored_by_bot(message, thread):
                continue
            text = (message.content or "").strip()
            if has_import_placeholder(text) and not message.attachments:
                continue
            if text or message.attachments:
                return True
    except (discord.Forbidden, discord.HTTPException):
        return False
    return False


async def _fill_thread(
    thread: discord.Thread,
    starter: discord.Message | None,
    chunks: list[str],
    *,
    existing_followups: list[discord.Message] | None = None,
) -> None:
    if not chunks:
        return
    await _unarchive(thread)
    if starter is None:
        starter = await resolve_starter(thread)
    if starter is not None:
        try:
            await starter.edit(content=chunks[0])
        except discord.HTTPException:
            starter = None
    if starter is None:
        try:
            await thread.send(chunks[0])
        except discord.HTTPException:
            return
        followup_chunks = chunks[1:]
        known: list[discord.Message] = []
        allow_new = True
    else:
        followup_chunks = chunks[1:]
        if existing_followups is not None:
            known = existing_followups
            allow_new = True
        else:
            known = await _collect_followups(thread, starter)
            allow_new = not await _has_foreign_followups(thread, starter)
    for index, chunk in enumerate(followup_chunks):
        if index < len(known):
            try:
                await known[index].edit(content=chunk)
                continue
            except discord.HTTPException:
                pass
        if not allow_new:
            break
        try:
            await thread.send(chunk)
        except discord.HTTPException:
            break


async def _emit(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress is not None:
        await on_progress(message)


async def import_wiki_cluster(
    *,
    guild: discord.Guild,
    root: WikiPage,
    limit: int = MAX_IMPORT_PAGES,
    follow_links: bool = False,
    on_progress: ProgressCallback | None = None,
) -> WikiImportResult:
    lock = _lock_for(guild.id)
    if lock.locked():
        raise WikiError("Un import ou un repair wiki est déjà en cours sur ce serveur.")
    async with lock:
        return await _import_wiki_cluster(
            guild=guild,
            root=root,
            limit=limit,
            follow_links=follow_links,
            on_progress=on_progress,
        )


async def _import_wiki_cluster(
    *,
    guild: discord.Guild,
    root: WikiPage,
    limit: int,
    follow_links: bool,
    on_progress: ProgressCallback | None,
) -> WikiImportResult:
    await ensure_default_campaign_forums(guild)
    cluster = await fetch_wiki_cluster(
        root,
        limit=limit,
        depth=1 if follow_links else 0,
        infobox_only=follow_links,
        on_progress=on_progress,
    )
    pages, aliases, truncated = cluster.pages, cluster.aliases, cluster.truncated
    forums_by_section: dict[str, discord.ForumChannel] = {}
    for page in pages:
        if page.section not in forums_by_section:
            forums_by_section[page.section] = await ensure_campaign_forum(
                guild, page.section
            )

    forums = list_campaign_forums(guild)
    posts: list[ImportedPost] = []
    starters: dict[int, discord.Message] = {}
    followups: dict[int, list[discord.Message]] = {}
    total = len(pages)

    for index, page in enumerate(pages, start=1):
        forum = forums_by_section[page.section]
        existing = await locate_campaign_thread(forums, page.title)
        if existing is not None:
            starter = await resolve_starter(existing)
            needs_fill = await thread_needs_wiki_fill(existing, starter)
            posts.append(
                ImportedPost(
                    page=page,
                    thread=existing,
                    forum=forum,
                    created=False,
                    needs_fill=needs_fill,
                )
            )
            if starter is not None:
                starters[existing.id] = starter
            continue

        await _emit(
            on_progress, f"🧵 Création des posts… **{index}/{total}** (`{page.title}`)"
        )
        image = (
            await download_thumbnail(page.thumbnail_url) if page.thumbnail_url else None
        )
        chunks = page.discord_chunks()
        kwargs: dict = {
            "name": page.title[:100],
            "content": chunks[0] if chunks else f"**{page.title}**",
        }
        if image is not None:
            kwargs["file"] = image
        created = await forum.create_thread(**kwargs)
        starter = created.message
        if starter is None:
            starter = await resolve_starter(created.thread)
        sent: list[discord.Message] = []
        for chunk in chunks[1:]:
            try:
                sent.append(await created.thread.send(chunk))
            except discord.HTTPException:
                break
        posts.append(
            ImportedPost(
                page=page,
                thread=created.thread,
                forum=forum,
                created=True,
                needs_fill=True,
            )
        )
        if starter is not None:
            starters[created.thread.id] = starter
        followups[created.thread.id] = sent
        forums = list_campaign_forums(guild)
        await asyncio.sleep(0.45)

    jump_urls = {post.page.title: post.thread.jump_url for post in posts}
    sections = {post.page.title.casefold(): post.forum.name for post in posts}
    for requested, canonical in aliases.items():
        url = jump_urls.get(canonical)
        if url and requested not in jump_urls:
            jump_urls[requested] = url
        forum_name = sections.get(canonical.casefold())
        if forum_name:
            sections[requested.casefold()] = forum_name

    root_key = root.title.casefold()
    to_fill = [
        post
        for post in posts
        if post.created
        or post.needs_fill
        or (follow_links and post.page.title.casefold() == root_key)
    ]
    for index, post in enumerate(to_fill, start=1):
        extra = () if post.page.title.casefold() == root_key else (root.title,)
        rewritten = _rewrite_page(post.page, jump_urls, sections, extra_outgoing=extra)
        await _emit(
            on_progress,
            f"🔗 Mise à jour des liens… **{index}/{len(to_fill)}** (`{post.page.title}`)",
        )
        await _fill_thread(
            post.thread,
            starters.get(post.thread.id),
            rewritten.discord_chunks(),
            existing_followups=followups.get(post.thread.id),
        )
        await asyncio.sleep(_FILL_DELAY)

    return WikiImportResult(
        posts=posts,
        truncated=truncated,
        max_pages=limit,
        missing_wiki=cluster.missing,
        failed_wiki=cluster.failed,
    )


async def repair_placeholder_posts(
    guild: discord.Guild,
    *,
    on_progress: ProgressCallback | None = None,
) -> RepairResult:
    lock = _lock_for(guild.id)
    if lock.locked():
        raise WikiError("Un import ou un repair wiki est déjà en cours sur ce serveur.")
    async with lock:
        return await _repair_placeholder_posts(guild, on_progress=on_progress)


async def _repair_placeholder_posts(
    guild: discord.Guild,
    *,
    on_progress: ProgressCallback | None,
) -> RepairResult:
    await ensure_default_campaign_forums(guild)
    forums = list_campaign_forums(guild)
    jump_urls: dict[str, str] = {}
    sections: dict[str, str] = {}
    pending: list[tuple[discord.Thread, discord.Message]] = []

    for forum in forums:
        for thread in await iter_forum_threads(forum):
            jump_urls[thread.name] = thread.jump_url
            sections[thread.name.casefold()] = forum.name
            if thread.archived and getattr(thread, "locked", False):
                continue
            starter = await resolve_starter(thread)
            if starter is not None and await thread_needs_wiki_fill(thread, starter):
                pending.append((thread, starter))

    repaired: list[discord.Thread] = []
    missing: list[str] = []
    total = len(pending)
    for index, (thread, starter) in enumerate(pending, start=1):
        await _emit(
            on_progress, f"🔧 Remplissage… **{index}/{total}** (`{thread.name}`)"
        )
        try:
            page = await fetch_wiki_page(thread.name, suggest=False)
        except (WikiNotFoundError, WikiError):
            missing.append(thread.name)
            await asyncio.sleep(_WIKI_DELAY)
            continue
        rewritten = _rewrite_page(page, jump_urls, sections)
        await _fill_thread(thread, starter, rewritten.discord_chunks())
        repaired.append(thread)
        await asyncio.sleep(_WIKI_DELAY)

    return RepairResult(
        repaired=repaired,
        missing_wiki=tuple(missing),
        scanned=total,
    )
