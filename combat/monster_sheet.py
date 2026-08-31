from __future__ import annotations

import re

import discord

from combat.storage import CombatState
from srd import fivetools
from srd.embeds import monster_embed
from srd.fivetools.lookup import lookup_candidates
from srd.search_view import SrdMatchView, build_match_prompt

_COPY_SUFFIX = re.compile(r"\s+\d+$")


def display_monster_name(name: str) -> str:
    """Strip numbered copies so 'Goblin 2' looks up Goblin."""
    return _COPY_SUFFIX.sub("", name).strip()


def npc_sheet_names(state: CombatState) -> list[str]:
    """Unique NPC names in turn order, without copy suffixes."""
    seen: set[str] = set()
    names: list[str] = []
    for name in state.turn_order:
        combatant = state.combatants.get(name.lower())
        if combatant is None or combatant.user_id is not None:
            continue
        base = display_monster_name(combatant.name)
        key = base.casefold()
        if not base or key in seen:
            continue
        seen.add(key)
        names.append(base)
    return names


def preferred_sheet_name(state: CombatState) -> str | None:
    """Active NPC if any, otherwise the only NPC type in the fight."""
    active = state.active_combatant()
    if active is not None and active.user_id is None:
        return display_monster_name(active.name)
    names = npc_sheet_names(state)
    if len(names) == 1:
        return names[0]
    return None


async def load_monster_sheet(
    query: str,
) -> tuple[discord.Embed | None, discord.ui.View | None, str | None]:
    """Return (embed, picker, error) for an SRD monster lookup."""
    text = display_monster_name(query)
    if not text:
        return None, None, "No monster name."
    try:
        candidates = lookup_candidates("monster", text)
        if candidates is not None:
            if not candidates:
                return None, None, f"No monster found matching '{text}'."
            if len(candidates) > 1:
                return (
                    build_match_prompt(query=text, matches=candidates),
                    SrdMatchView(kind="monster", matches=candidates),
                    None,
                )
            item = await fivetools.search_monster(
                query=str(candidates[0].get("name") or text)
            )
        else:
            item = await fivetools.search_monster(query=text)
        return monster_embed(item), None, None
    except fivetools.FiveToolsError as exc:
        return None, None, str(exc)
