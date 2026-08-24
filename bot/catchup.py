import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.utils import snowflake_time

from config import CATCHUP_ENABLED, CATCHUP_MAX_AGE_HOURS, CATCHUP_MAX_MESSAGES, PREFIX
from data.db import mark_channel_message_processed

logger = logging.getLogger(__name__)

_processed_this_session: set[int] = set()
_catchup_active = False
_MAX_PAGES_PER_CHANNEL = 10

# State-changing commands that must not replay after downtime.
CATCHUP_BLOCKED_COMMANDS: frozenset[str] = frozenset(
    {
        "sheet create",
        "sheet delete",
        "sheet import",
        "sheet set",
        "sheet hp",
        "sheet money set",
        "sheet money add",
        "sheet money spend",
        "sheet money pay",
        "sheet prof save",
        "sheet prof skill",
        "sheet spells add",
        "sheet spells remove",
        "sheet slots use",
        "sheet slots recover",
        "sheet slots set",
        "sheet slots auto",
        "sheet slots clear",
        "sheet condition",
        "sheet inspire",
        "sheet deathsave",
        "sheet rest short",
        "sheet rest long",
        "sheet gear",
        "combat",
        "party money set",
        "party money add",
        "party money spend",
        "init add",
        "init next",
        "init clear",
        "init remove",
        "pcname",
        "npc",
        "campaign",
        "lore",
        "camp",
        "time",
        "clock",
        "calendar",
        "date",
        "temps",
        "hunger",
        "faim",
        "food",
        "image",
        "player setup",
        "player add",
        "player create",
        "player sync",
        "player remove",
        "player delete",
    }
)


def is_catchup_active() -> bool:
    return _catchup_active


def is_catchup_invoke(ctx: commands.Context) -> bool:
    return bool(getattr(ctx, "_from_catchup", False))


def mark_message_processed(*, channel_id: int, message_id: int) -> None:
    mark_channel_message_processed(channel_id=channel_id, message_id=message_id)
    _processed_this_session.add(message_id)


def reset_session_tracking() -> None:
    _processed_this_session.clear()


def _is_catchup_allowed(ctx: commands.Context) -> bool:
    if ctx.command is None:
        return False
    if ctx.message.attachments:
        return False
    name = ctx.command.qualified_name
    if name in CATCHUP_BLOCKED_COMMANDS:
        return False
    return not any(
        name.startswith(f"{blocked} ") for blocked in CATCHUP_BLOCKED_COMMANDS
    )


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


async def _process_catchup_message(bot: Bot, message: discord.Message) -> bool:
    if message.id in _processed_this_session:
        return False
    if message.author.bot or not message.content.startswith(PREFIX):
        return False
    if message.guild is None:
        return False

    ctx = await bot.get_context(message)
    ctx._from_catchup = True
    if ctx.command is None:
        return False

    if not _is_catchup_allowed(ctx):
        mark_message_processed(channel_id=message.channel.id, message_id=message.id)
        return False

    try:
        await bot.invoke(ctx)
    except commands.CommandInvokeError:
        return False

    mark_message_processed(channel_id=message.channel.id, message_id=message.id)
    return True


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
    if isinstance(channel, discord.Thread) and isinstance(
        channel.parent, discord.ForumChannel
    ):
        return 0

    try:
        permissions = channel.permissions_for(me)
    except discord.ClientException:
        return 0
    if not permissions.view_channel or not permissions.read_message_history:
        return 0

    after: discord.Object | datetime = _catchup_after(channel.id, last_ids)
    processed = 0
    last_seen_id: int | None = None
    page_size = max(int(CATCHUP_MAX_MESSAGES), 1)

    try:
        for _ in range(_MAX_PAGES_PER_CHANNEL):
            page: list[discord.Message] = []
            async for message in channel.history(
                after=after,
                oldest_first=True,
                limit=page_size,
            ):
                page.append(message)
            if not page:
                break
            for message in page:
                last_seen_id = message.id
                if await _process_catchup_message(bot=bot, message=message):
                    processed += 1
            after = discord.Object(id=page[-1].id)
            if len(page) < page_size:
                break
    except (discord.Forbidden, discord.HTTPException, discord.ClientException):
        pass

    if last_seen_id is not None:
        mark_message_processed(channel_id=channel.id, message_id=last_seen_id)
    return processed


async def _iter_catchup_channels(guild: discord.Guild) -> list[discord.abc.Messageable]:
    channels: list[discord.abc.Messageable] = list(guild.text_channels)

    for text_channel in guild.text_channels:
        channels.extend(text_channel.threads)
        try:
            async for thread in text_channel.archived_threads(limit=25):
                channels.append(thread)
        except (discord.Forbidden, discord.HTTPException):
            pass

    return channels


async def catch_up_missed_commands(bot: Bot) -> int:
    global _catchup_active

    if not CATCHUP_ENABLED:
        logger.info("Catch-up disabled.")
        return 0

    processed = 0
    last_ids: dict[str, int] = {}

    from data.db import get_json

    stored = get_json("last_message_ids")
    if isinstance(stored, dict):
        last_ids = {str(key): int(value) for key, value in stored.items()}

    logger.info("Catch-up started.")
    _catchup_active = True
    try:
        for guild in bot.guilds:
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
    finally:
        _catchup_active = False

    logger.info("Catch-up finished: replayed %s missed command(s).", processed)
    return processed
