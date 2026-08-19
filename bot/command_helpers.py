import logging

from discord.errors import Forbidden, HTTPException, NotFound
from discord.ext.commands.context import Context

from bot.messaging import send_reply

logger = logging.getLogger(__name__)


async def delete_command(ctx: Context) -> None:
    if ctx.interaction is not None:
        return
    try:
        await ctx.message.delete()
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
