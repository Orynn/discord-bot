import discord
from discord.abc import User
from discord.ext.commands import check
from discord.ext.commands.context import Context

from config import STAFF_USER_IDS, STAFF_USERNAMES


async def _admin_only_predicate(ctx: Context) -> bool:
    return is_admin(ctx)


admin_only = check(_admin_only_predicate)


def _as_member(
    guild: discord.Guild | None, user: User | discord.Member | None
) -> discord.Member | None:
    if isinstance(user, discord.Member):
        return user
    if guild is None or user is None:
        return None
    return guild.get_member(user.id)


def is_admin_member(
    guild: discord.Guild | None, user: User | discord.Member | None
) -> bool:
    member = _as_member(guild, user)
    if guild is None or member is None:
        return False
    if guild.owner_id == member.id:
        return True
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild


def is_admin(ctx: Context) -> bool:
    return is_admin_member(ctx.guild, ctx.author)


def is_staff_user_id(user_id: int) -> bool:
    return user_id in STAFF_USER_IDS


def is_staff_member(
    guild: discord.Guild | None, user: User | discord.Member | None
) -> bool:
    if user is None:
        return False
    if is_staff_user_id(user.id):
        return True
    member = _as_member(guild, user)
    if is_admin_member(guild, member or user):
        return True
    names = [
        getattr(user, "name", None),
        getattr(user, "display_name", None),
        getattr(user, "global_name", None),
        getattr(user, "nick", None),
    ]
    return any(str(name).casefold() in STAFF_USERNAMES for name in names if name)


def is_staff(ctx: Context) -> bool:
    return is_staff_member(ctx.guild, ctx.author)


async def _guild_only_predicate(ctx: Context) -> bool:
    return ctx.guild is not None


guild_only = check(_guild_only_predicate)
