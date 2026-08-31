from typing import Any

from players.discover import discover_player_id, sandbox_scope_id

PLAYER_COMBAT_ONLY = (
    "Le combat ne tourne que dans une section joueur (OOC ou roleplay) ou #🚯trash."
)
PLAYER_INIT_ONLY = (
    "L’initiative ne tourne que dans une section joueur (OOC ou roleplay) ou #🚯trash."
)


def scope_id_for_channel(*, guild: Any, channel: Any) -> int | None:
    if guild is None or channel is None:
        return None
    sandbox = sandbox_scope_id(channel)
    if sandbox is not None:
        return sandbox
    return discover_player_id(guild=guild, channel=channel)
