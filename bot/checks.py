import discord
from discord.ext.commands import check
from discord.ext.commands.context import Context


async def _admin_only_predicate(ctx: Context) -> bool:
    return is_admin(ctx)


admin_only = check(_admin_only_predicate)


def is_admin(ctx: Context) -> bool:
    if ctx.guild is None or not isinstance(ctx.author, discord.Member):
        return False
    if ctx.guild.owner_id == ctx.author.id:
        return True
    perms = ctx.author.guild_permissions
    return perms.administrator or perms.manage_guild


async def _guild_only_predicate(ctx: Context) -> bool:
    return ctx.guild is not None


guild_only = check(_guild_only_predicate)
