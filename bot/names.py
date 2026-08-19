from npc.storage import get_npc_names
from sheets.storage import get_all_pc_names, get_all_sheet_names


def get_known_character_names() -> list[str]:
    names = get_all_pc_names() | get_all_sheet_names() | get_npc_names()
    return sorted(names, key=len, reverse=True)
