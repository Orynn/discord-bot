import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

import discord
from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.utils import snowflake_time

from bot.rate_limits import (
    is_rate_limited,
    retry_on_rate_limit,
    should_retry_rate_limit,
    sleep_discord_retry,
)
from config import (
    CATCHUP_ENABLED,
    CATCHUP_MAX_AGE_HOURS,
    CATCHUP_MAX_MESSAGES,
    PREFIX,
    is_home_guild,
)
from data.db import get_json, mark_channel_message_processed

logger = logging.getLogger(__name__)

_processed_this_session: set[int] = set()
_MAX_PAGES_PER_CHANNEL = 10
_ARCHIVE_LIST_CONCURRENCY = 4
# Commands whose meaning depends on *when* they run. `;purge 20` replayed hours
# later would delete the 20 messages posted since, not the ones it targeted.
_NEVER_REPLAY: frozenset[str] = frozenset({"purge"})


def is_catchup_invoke(ctx: commands.Context) -> bool:
    return getattr(ctx, "_from_catchup", False) is True


def mark_message_processed(*, channel_id: int, message_id: int) -> None:
    mark_channel_message_processed(channel_id=channel_id, message_id=message_id)
    _processed_this_session.add(message_id)


def reset_session_tracking() -> None:
    _processed_this_session.clear()


async def _history_page(
    channel: discord.abc.Messageable,
    *,
    after: discord.Object | datetime,
    page_size: int,
) -> list[discord.Message]:
    page: list[discord.Message] = []
    async for message in channel.history(
        after=after,
        oldest_first=True,
        limit=page_size,
    ):
        page.append(message)
    return page


async def _list_archived_threads(
    parent: discord.TextChannel | discord.ForumChannel,
) -> list[discord.Thread]:
    # A thread archived before the catch-up window cannot hold missed messages.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CATCHUP_MAX_AGE_HOURS)

    async def collect() -> list[discord.Thread]:
        threads: list[discord.Thread] = []
        async for thread in parent.archived_threads(limit=25):
            archived_at = getattr(thread, "archive_timestamp", None)
            if isinstance(archived_at, datetime) and archived_at < cutoff:
                break
            threads.append(thread)
        return threads

    try:
        return await retry_on_rate_limit(collect)
    except (discord.Forbidden, discord.HTTPException, discord.ClientException):
        return []


def _catchup_after(
    channel_id: int, last_ids: dict[str, int]
) -> discord.Object | datetime:
    min_after = datetime.now(timezone.utc) - timedelta(hours=CATCHUP_MAX_AGE_HOURS)
    last_id = last_ids.get(str(channel_id))
    if last_id is None:
        return min_after
    last_dt = snowflake_time(last_id)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    if last_dt < min_after:
        return min_after
    return discord.Object(id=last_id)


async def _process_catchup_message(
    bot: Bot, message: discord.Message
) -> Literal["replayed", "skipped"]:
    if message.id in _processed_this_session:
        return "skipped"
    if message.author.bot or not message.content.startswith(PREFIX):
        return "skipped"
    if message.guild is None:
        return "skipped"

    ctx = await bot.get_context(message)
    ctx._from_catchup = True
    if ctx.command is None:
        return "skipped"
    if ctx.command.qualified_name.split()[0] in _NEVER_REPLAY:
        logger.info(
            "Catch-up skipped time-sensitive command %s (message %s).",
            ctx.command.qualified_name,
            message.id,
        )
        mark_message_processed(channel_id=message.channel.id, message_id=message.id)
        return "skipped"

    # Every other command is replayed. Errors are handled (and shown) by
    # on_command_error like a live call; a failure never blocks the channel.
    try:
        await bot.invoke(ctx)
    except Exception:
        logger.exception("Catch-up replay failed for message %s", message.id)

    mark_message_processed(channel_id=message.channel.id, message_id=message.id)
    return "replayed"


async def _catch_up_channel(
    bot: Bot,
    channel: discord.abc.Messageable,
    *,
    last_ids: dict[str, int],
) -> int:
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        return 0

    me = channel.guild.me if channel.guild else None
    if me is None:
        return 0
    if isinstance(channel, discord.Thread) and channel.parent is None:
        return 0

    try:
        permissions = channel.permissions_for(me)
    except discord.ClientException:
        return 0
    if not permissions.view_channel or not permissions.read_message_history:
        return 0

    stored_id = last_ids.get(str(channel.id))
    latest_id = getattr(channel, "last_message_id", None)
    if stored_id is not None and isinstance(latest_id, int) and latest_id <= stored_id:
        # Nothing was posted since the last processed message: skip the API call.
        return 0

    after: discord.Object | datetime = _catchup_after(channel.id, last_ids)
    processed = 0
    last_seen_id: int | None = None
    page_size = max(int(CATCHUP_MAX_MESSAGES), 1)

    try:
        for _ in range(_MAX_PAGES_PER_CHANNEL):
            try:
                page = await _history_page(channel, after=after, page_size=page_size)
            except discord.Forbidden:
                break
            except discord.HTTPException as exc:
                if should_retry_rate_limit(exc):
                    await sleep_discord_retry(exc)
                    continue
                if is_rate_limited(exc):
                    logger.warning(
                        "Catch-up stopped on channel %s after Discord 429.",
                        channel.id,
                    )
                break
            except discord.ClientException:
                break
            if not page:
                break
            for message in page:
                result = await _process_catchup_message(bot=bot, message=message)
                last_seen_id = message.id
                if result == "replayed":
                    processed += 1
            after = discord.Object(id=page[-1].id)
            if len(page) < page_size:
                break
    except discord.ClientException:
        pass

    if last_seen_id is not None:
        mark_message_processed(channel_id=channel.id, message_id=last_seen_id)
    return processed


async def _iter_catchup_channels(guild: discord.Guild) -> list[discord.abc.Messageable]:
    channels: list[discord.abc.Messageable] = list(guild.text_channels)

    parents = [*guild.text_channels, *getattr(guild, "forums", [])]
    limit = asyncio.Semaphore(_ARCHIVE_LIST_CONCURRENCY)

    async def archived(parent) -> list[discord.Thread]:
        async with limit:
            return await _list_archived_threads(parent)

    # One archive listing per parent, a few at a time instead of one by one.
    archived_lists = await asyncio.gather(*(archived(parent) for parent in parents))
    for parent, archived_threads in zip(parents, archived_lists, strict=True):
        channels.extend(parent.threads)
        channels.extend(archived_threads)

    return channels


async def catch_up_missed_commands(bot: Bot) -> int:
    if not CATCHUP_ENABLED:
        logger.info("Catch-up disabled.")
        return 0

    processed = 0
    last_ids: dict[str, int] = {}
    stored = get_json("last_message_ids")
    if isinstance(stored, dict):
        last_ids = {str(key): int(value) for key, value in stored.items()}

    logger.info("Catch-up started.")
    for guild in bot.guilds:
        if not is_home_guild(guild):
            continue
        seen: set[int] = set()
        for channel in await _iter_catchup_channels(guild):
            if channel.id in seen:
                continue
            seen.add(channel.id)
            try:
                processed += await _catch_up_channel(
                    bot=bot, channel=channel, last_ids=last_ids
                )
            except discord.ClientException:
                continue

    logger.info("Catch-up finished: replayed %s missed command(s).", processed)
    return processed
