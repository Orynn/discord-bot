from typing import Any

from data.db import get_json, set_json

_STORE_KEY = "player_sections"


def _guild_store(guild_id: int) -> dict[str, Any]:
    store = get_json(_STORE_KEY) or {}
    guild_store = store.get(str(guild_id), {})
    return dict(guild_store) if isinstance(guild_store, dict) else {}


def get_player_section(*, guild_id: int, user_id: int) -> dict[str, Any] | None:
    entry = _guild_store(guild_id).get(str(user_id))
    return entry if isinstance(entry, dict) else None


def list_player_sections(*, guild_id: int) -> list[tuple[int, dict[str, Any]]]:
    entries: list[tuple[int, dict[str, Any]]] = []
    for user_id, record in _guild_store(guild_id).items():
        if isinstance(record, dict):
            entries.append((int(user_id), record))
    return sorted(entries, key=lambda item: item[1].get("name", "").lower())


def save_player_section(*, guild_id: int, user_id: int, data: dict[str, Any]) -> None:
    store = get_json(_STORE_KEY) or {}
    guild_store = _guild_store(guild_id)
    guild_store[str(user_id)] = data
    store[str(guild_id)] = guild_store
    set_json(_STORE_KEY, store)


def delete_player_section(*, guild_id: int, user_id: int) -> dict[str, Any] | None:
    store = get_json(_STORE_KEY) or {}
    guild_store = _guild_store(guild_id)
    removed = guild_store.pop(str(user_id), None)
    if removed is None:
        return None
    store[str(guild_id)] = guild_store
    set_json(_STORE_KEY, store)
    return removed if isinstance(removed, dict) else None
