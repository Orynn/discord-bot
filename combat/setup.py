from __future__ import annotations

import random

from campaign.clock import format_duration, parse_duration
from campaign.clock_storage import get_clock, save_clock
from combat.monsters import lookup_monster_profile
from combat.templates import known_map_ids
from sheets.hunger import tick_hunger_for_clock
from initiative.storage import (
    InitiativeState,
    add_initiative_entry,
    get_initiative,
    save_initiative,
)
from sheets.data import ability_modifier
from sheets.storage import get_sheet


def parse_start_args(
    text: str, *, guild_id: int | None = None
) -> tuple[str | None, int | None, str]:
    """Split `;combat start Dire Wolf tavern 2h` into monster, minutes, and map."""
    cleaned = text.strip()
    if not cleaned:
        return None, None, "arena"
    parts = cleaned.split()
    minutes = None
    last = parts[-1].lstrip("+")
    try:
        minutes = parse_duration(last)
        parts = parts[:-1]
    except ValueError:
        pass
    map_id = "arena"
    known = known_map_ids(guild_id=guild_id)
    if parts and parts[-1].lower() in known:
        map_id = parts[-1].lower()
        parts = parts[:-1]
    name = " ".join(parts).strip() or None
    return name, minutes, map_id


def _already_listed(
    state: InitiativeState, *, name: str | None = None, user_id: int | None = None
) -> bool:
    for entry in state.order:
        if user_id is not None and entry.user_id == user_id:
            return True
        if name and entry.name.casefold() == name.casefold():
            return True
    return False


async def ensure_section_fight(
    *,
    guild_id: int,
    channel_id: int,
    scope_id: int,
    player_id: int | None,
    monster_name: str | None,
) -> InitiativeState:
    state = get_initiative(guild_id=guild_id, scope_id=scope_id)
    if state is None:
        state = InitiativeState(channel_id=channel_id, active_index=0, order=[])

    if player_id is not None and not _already_listed(state, user_id=player_id):
        sheet = get_sheet(user_id=player_id, guild_id=guild_id)
        name = sheet.name if sheet and sheet.name else "Player"
        modifier = ability_modifier(sheet.abilities["dex"]) if sheet else 0
        roll = random.randint(1, 20)
        add_initiative_entry(state, name=name, total=roll + modifier, user_id=player_id)

    if monster_name and not _already_listed(state, name=monster_name):
        monster = await lookup_monster_profile(monster_name)
        label = monster.name if monster is not None else monster_name
        roll = random.randint(1, 20)
        add_initiative_entry(state, name=label, total=roll, user_id=None)

    if not state.order:
        raise ValueError(
            "Pas d’initiative. Utilise `;init add`, puis `;combat start`."
        )

    save_initiative(guild_id=guild_id, scope_id=scope_id, state=state)
    return state


def advance_section_clock(*, guild_id: int, user_id: int, minutes: int) -> str:
    previous = get_clock(guild_id, user_id)
    clock = previous.advance(minutes)
    save_clock(guild_id, user_id, clock)
    tick_hunger_for_clock(
        guild_id=guild_id,
        user_id=user_id,
        previous=previous,
        current=clock,
    )
    return f"Horloge +{format_duration(minutes)} → {clock.format_date()} · {clock.format_clock()}"
