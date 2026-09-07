import logging

from discord.errors import Forbidden, HTTPException, NotFound
from discord.ext.commands.context import Context

from bot.messaging import send_reply
from bot.rate_limits import retry_on_rate_limit

logger = logging.getLogger(__name__)

SERVER_ONLY = "Cette commande marche seulement sur le serveur."


async def defer_if_slash(ctx: Context, *, ephemeral: bool = False) -> None:
    if ctx.interaction is not None and not ctx.interaction.response.is_done():
        await ctx.defer(ephemeral=ephemeral)


async def delete_command(ctx: Context) -> None:
    if ctx.interaction is not None:
        deferred_here = False
        if not ctx.interaction.response.is_done():
            try:
                await ctx.defer(ephemeral=True)
                deferred_here = True
            except (HTTPException, NotFound):
                pass
        if deferred_here:
            try:
                await ctx.interaction.delete_original_response()
            except (HTTPException, NotFound):
                pass
        return
    try:
        await retry_on_rate_limit(ctx.message.delete)
    except (Forbidden, NotFound):
        pass
    except TimeoutError:
        logger.warning(
            "Timed out deleting command message in channel %s (message %s)",
            ctx.channel.id,
            ctx.message.id,
        )
    except HTTPException as exc:
        if exc.status == 404:
            return
        logger.warning("Failed to delete command message: %s", exc)


async def command_reply(
    ctx: Context,
    message: str,
    *,
    linkify: bool = True,
    definition_menu: bool = True,
) -> None:
    await send_reply(
        ctx,
        message,
        linkify=linkify,
        definition_menu=definition_menu,
    )
