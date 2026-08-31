import discord
from discord.ext.commands.context import Context

from bot.checks import is_staff
from bot.command_helpers import command_reply, delete_command

DENIED_OTHER_PLAYER = "Tu ne peux pas consulter la fiche d’un autre joueur."
MISSING_PLAYER_TARGET = "Mentionne @joueur, ou lance la commande dans sa section."


def targets_other_player(ctx: Context, member: discord.Member | None) -> bool:
    return member is not None and member.id != ctx.author.id and not is_staff(ctx)


async def reject_other_player(
    ctx: Context,
    member: discord.Member | None,
    *,
    delete: bool = False,
) -> bool:
    """Return True if the caller may access this player's data."""
    if not targets_other_player(ctx, member):
        return True
    await command_reply(ctx, DENIED_OTHER_PLAYER)
    if delete:
        await delete_command(ctx)
    return False
