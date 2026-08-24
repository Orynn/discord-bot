from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import command_reply, delete_command
from bot.messaging import send_message
from bot.speech import format_npc_speech, parse_dialogue
from config import PREFIX
from sheets.context import resolve_guild_id, resolve_owner
from sheets.storage import get_character_name, set_character_name


def setup_pc(bot: Bot) -> None:
    @bot.hybrid_command(
        name="pcname",
        help="Set your character name.",
    )
    async def pcname_command(ctx: Context, *, name: str) -> None:
        name = name.strip()
        if not name:
            await command_reply(
                ctx, f"Character name cannot be empty. Usage: `{PREFIX}pcname <name>`"
            )
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "This command can only be used in a server.")
            return

        owner_id = await resolve_owner(ctx, None)
        if owner_id is None:
            return

        set_character_name(user_id=owner_id, guild_id=guild_id, name=name)
        await command_reply(ctx, f"Character name set to **{name}**.")
        await delete_command(ctx)

    @bot.hybrid_command(
        name="pc",
        aliases=["speak"],
        help="Speak in character. Optional (action) before dialogue.",
    )
    async def pc_command(ctx: Context, *, dialogue: str) -> None:
        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, "This command can only be used in a server.")
            return

        owner_id = await resolve_owner(ctx, None)
        if owner_id is None:
            return

        character_name = get_character_name(user_id=owner_id, guild_id=guild_id)
        if character_name is None:
            await command_reply(
                ctx,
                f"You have no character name set. Use `{PREFIX}pcname <name>` first.",
            )
            return

        action, dialogue = parse_dialogue(text=dialogue)
        await send_message(
            ctx,
            content=format_npc_speech(
                name=character_name,
                dialogue=dialogue,
                action=action,
            ),
            linkify=False,
            definition_menu=False,
        )
        await delete_command(ctx)
