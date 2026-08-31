from discord.ext.commands.bot import Bot
from discord.ext.commands.context import Context

from bot.command_helpers import SERVER_ONLY, command_reply, delete_command
from bot.help_text import command_help
from bot.messaging import send_message
from bot.speech import format_npc_speech, parse_dialogue
from config import PREFIX
from pc.identity import resolve_acting_character
from scene.commands import maybe_send_parenthetical_desc
from scene.state import mark_present
from sheets.context import resolve_guild_id, resolve_owner
from sheets.storage import set_character_name


def setup_pc(bot: Bot) -> None:
    @bot.hybrid_command(
        name="pcname",
        help=command_help(
            "Définit le nom de ton personnage.",
            f"`{PREFIX}pcname <nom>`",
        ),
    )
    async def pcname_command(ctx: Context, *, name: str) -> None:
        name = name.strip()
        if not name:
            await command_reply(
                ctx,
                f"Le nom du personnage ne peut pas être vide. `{PREFIX}pcname <nom>`",
            )
            return

        guild_id = resolve_guild_id(ctx)
        if guild_id is None:
            await command_reply(ctx, SERVER_ONLY)
            return

        owner_id = await resolve_owner(ctx, None)
        if owner_id is None:
            return

        set_character_name(user_id=owner_id, guild_id=guild_id, name=name)
        await command_reply(ctx, f"Personnage nommé **{name}**.")
        await delete_command(ctx)

    @bot.hybrid_command(
        name="pc",
        aliases=["speak"],
        help=command_help(
            "Parle en personnage. `(action)` optionnelle avant le dialogue.",
            f"`{PREFIX}pc <texte>`",
            f"`{PREFIX}pc (action)` — comme `{PREFIX}desc`",
        ),
    )
    async def pc_command(ctx: Context, *, dialogue: str) -> None:
        if await maybe_send_parenthetical_desc(ctx, dialogue):
            return

        resolved = await resolve_acting_character(ctx)
        if resolved is None:
            return
        guild_id, owner_id, character_name = resolved

        channel_id = getattr(ctx.channel, "id", None)
        if ctx.guild is not None and channel_id is not None:
            mark_present(
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=owner_id,
                name=character_name,
            )

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
