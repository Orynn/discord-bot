from npc.storage import get_npc_names
from sheets.storage import get_all_pc_names, get_all_sheet_names


def get_known_character_names(*, guild_id: int) -> list[str]:
    names = get_all_pc_names(guild_id=guild_id) | get_all_sheet_names(guild_id=guild_id) | get_npc_names(
        guild_id=guild_id
    )
    return sorted(names, key=len, reverse=True)
