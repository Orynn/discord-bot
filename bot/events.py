import logging

import discord
from discord.ext import commands
from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.catchup import (
    catch_up_missed_commands,
    is_catchup_invoke,
    mark_message_processed,
    reset_session_tracking,
)
from bot.command_helpers import command_reply, delete_command
from bot.command_log import log_command
from bot.views import register_persistent_views
from campaign.forums import CampaignForumError, ensure_default_campaign_forums
from config import PREFIX
from players.discover import refresh_guild_player_sections, sync_guild_player_sections
from srd import fivetools, glossary
from srd.fivetools.paths import is_available

logger = logging.getLogger(__name__)


async def _error_reply(ctx: Context, message: str) -> None:
    try:
        await command_reply(ctx, message, linkify=False, definition_menu=False)
        await delete_command(ctx)
    except (discord.NotFound, discord.HTTPException):
        logger.warning("Could not send command error in %s: %s", ctx.channel, message)


def register_events(bot: Bot) -> None:
    @bot.event
    async def on_ready() -> None:
        logger.info("Logged in as %s", bot.user)
        reset_session_tracking()
        register_persistent_views(bot)

        async def _startup() -> None:
            for guild in bot.guilds:
                try:
                    mapped = sync_guild_player_sections(guild)
                    if mapped:
                        logger.info("Mapped %s player section(s) in %s.", mapped, guild.name)
                except Exception:
                    logger.exception("Could not map player sections in %s", guild.name)
                try:
                    forums = await ensure_default_campaign_forums(guild)
                    logger.info(
                        "Campaign forums ready in %s (%s).",
                        guild.name,
                        ", ".join(forum.name for forum in forums),
                    )
                except CampaignForumError as exc:
                    logger.warning("Could not create campaign forums in %s: %s", guild.name, exc)
                except (discord.Forbidden, discord.HTTPException):
                    logger.exception("Could not create campaign forums in %s", guild.name)

            if not is_available():
                logger.error(
                    "5etools data missing — bundle official JSON under 5etools/data/ "
                    "and/or export homebrew to 5etools/homebrew.json before using ;srd."
                )
            else:
                try:
                    index = await fivetools.ensure_index_loaded()
                    logger.info("5etools index loaded from %s.", ", ".join(index.loaded_sources))
                except Exception:
                    logger.exception("5etools index load failed")
                else:
                    try:
                        await glossary.load()
                    except Exception:
                        logger.exception("Rules glossary load failed")

            try:
                await catch_up_missed_commands(bot=bot)
            except Exception:
                logger.exception("Catch-up failed")

        bot.loop.create_task(_startup())

    def _refresh_sections(guild: discord.Guild | None) -> None:
        if guild is None:
            return
        try:
            refresh_guild_player_sections(guild)
        except Exception:
            logger.exception("Could not refresh player sections in %s", getattr(guild, "name", guild))

    @bot.event
    async def on_guild_available(guild: discord.Guild) -> None:
        _refresh_sections(guild)

    @bot.event
    async def on_guild_join(guild: discord.Guild) -> None:
        _refresh_sections(guild)

    @bot.event
    async def on_guild_channel_create(channel: discord.abc.GuildChannel) -> None:
        _refresh_sections(getattr(channel, "guild", None))

    @bot.event
    async def on_guild_channel_update(
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        _refresh_sections(getattr(after, "guild", None) or getattr(before, "guild", None))

    @bot.event
    async def on_guild_channel_delete(channel: discord.abc.GuildChannel) -> None:
        _refresh_sections(getattr(channel, "guild", None))

    @bot.event
    async def on_command_error(ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandNotFound):
            return

        if is_catchup_invoke(ctx):
            return

        if isinstance(error, commands.CommandOnCooldown):
            wait = max(1, int(error.retry_after + 0.999))
            await _error_reply(ctx, f"That command is on cooldown. Try again in {wait}s.")
            return

        if isinstance(error, commands.UserInputError):
            help_text = ctx.command.help if ctx.command and ctx.command.help else ""
            if isinstance(error, commands.MissingRequiredArgument):
                usage = ""
                if ctx.command is not None:
                    usage = f"\nUsage: `{PREFIX}{ctx.command.qualified_name} <{error.param.name}>`"
                message = f"Missing required argument: `{error.param.name}`.{usage}"
            else:
                message = "Invalid command usage."
            if help_text:
                message = f"{message}\n{help_text}"
            await _error_reply(ctx, message)
            return

        if isinstance(error, commands.CheckFailure):
            if ctx.guild is None:
                await _error_reply(ctx, "This command can only be used in a server.")
            else:
                await _error_reply(ctx, "You don't have permission to use this command.")
            return

        logger.exception("Unhandled command error in %s", ctx.command, exc_info=error)
        await _error_reply(ctx, "Something went wrong running that command.")

    @bot.event
    async def on_command_completion(ctx: Context) -> None:
        if is_catchup_invoke(ctx):
            return
        if ctx.interaction is not None:
            await log_command(ctx)
            return
        if ctx.guild is not None and ctx.message is not None:
            mark_message_processed(channel_id=ctx.channel.id, message_id=ctx.message.id)
        await log_command(ctx)
