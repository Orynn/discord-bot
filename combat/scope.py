from typing import Any

PLAYER_COMBAT_ONLY = "Card combat only runs in a player section (OOC or roleplay channel)."
PLAYER_INIT_ONLY = "Initiative only runs in a player section (OOC or roleplay channel)."


def scope_id_for_channel(*, guild: Any, channel: Any) -> int | None:
    if guild is None or channel is None:
        return None
    from players.discover import discover_player_id

    return discover_player_id(guild=guild, channel=channel)
