import discord
from discord.errors import Forbidden, HTTPException
from discord.ext.commands.context import Context

LOG_CHANNEL_NAME = "📜arkann-log"


async def log_command(ctx: Context) -> None:
    if ctx.guild is None or ctx.command is None:
        return

    log_channel = discord.utils.get(ctx.guild.text_channels, name=LOG_CHANNEL_NAME)
    if log_channel is None:
        return

    channel_ref = (
        ctx.channel.mention
        if isinstance(ctx.channel, discord.abc.GuildChannel)
        else "unknown"
    )
    message = (
        f"**{ctx.author.display_name}** (`{ctx.author.id}`) "
        f"used `{ctx.command.qualified_name}` in {channel_ref}\n"
        f"`{ctx.message.content}`"
    )
    try:
        await log_channel.send(message)
    except (Forbidden, HTTPException):
        pass
