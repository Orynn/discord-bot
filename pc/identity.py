from discord.ext.commands.context import Context

from bot.command_helpers import SERVER_ONLY, command_reply
from config import PREFIX
from sheets.context import resolve_guild_id, resolve_owner
from sheets.storage import find_user_id_by_character_name, get_character_name

NO_CHARACTER_NAME = (
    f"Tu n’as pas de nom de personnage. "
    f"`{PREFIX}sheet create <nom>` ou `{PREFIX}pcname <nom>` d’abord."
)
WHISPER_USAGE = (
    f"Usage : `{PREFIX}whisper @joueur <texte>` "
    f"ou `{PREFIX}chuchote <personnage> <texte>`."
)


async def resolve_acting_character(ctx: Context) -> tuple[int, int, str] | None:
    guild_id = resolve_guild_id(ctx)
    if guild_id is None:
        await command_reply(ctx, SERVER_ONLY)
        return None

    owner_id = await resolve_owner(ctx, None)
    if owner_id is None:
        return None

    name = (get_character_name(user_id=owner_id, guild_id=guild_id) or "").strip()
    if not name:
        await command_reply(ctx, NO_CHARACTER_NAME)
        return None
    return guild_id, owner_id, name


def resolve_whisper_target(
    *,
    guild_id: int,
    text: str,
    mentioned_id: int | None = None,
    mentioned_name: str | None = None,
) -> tuple[int, str, str] | None:
    rest = text.strip()
    if mentioned_id is not None:
        if not rest:
            return None
        name = (
            get_character_name(user_id=mentioned_id, guild_id=guild_id)
            or (mentioned_name or "").strip()
            or f"<@{mentioned_id}>"
        )
        return mentioned_id, name, rest

    tokens = rest.split()
    if len(tokens) < 2:
        return None
    for end in range(len(tokens) - 1, 0, -1):
        guess = " ".join(tokens[:end])
        user_id = find_user_id_by_character_name(guild_id=guild_id, name=guess)
        if user_id is None:
            continue
        message = " ".join(tokens[end:]).strip()
        if not message:
            return None
        name = get_character_name(user_id=user_id, guild_id=guild_id) or guess
        return user_id, name, message
    return None
