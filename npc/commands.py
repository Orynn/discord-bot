from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.checks import admin_only
from bot.command_helpers import delete_command
from bot.messaging import send_message
from bot.speech import format_npc_speech, parse_dialogue
from config import PREFIX
from npc.storage import register_npc_name


def setup_npc(bot: Bot) -> None:
    @bot.hybrid_command(
        name="npc",
        aliases=["say"],
        help="Make an NPC speak. Usage: name, then dialogue.",
    )
    @admin_only
    async def npc_command(ctx: Context, name: str, *, dialogue: str) -> None:
        name = register_npc_name(name=name)
        action, dialogue = parse_dialogue(text=dialogue)
        await send_message(
            ctx,
            content=format_npc_speech(name=name, dialogue=dialogue, action=action),
        )
        await delete_command(ctx)
