from __future__ import annotations

from dataclasses import dataclass

from combat.custom_maps import CustomMapData, get_custom_map, list_custom_maps


@dataclass(frozen=True)
class MapTemplate:
    map_id: str
    label: str
    blocked: tuple[tuple[int, int], ...]
    pc_column: int = 1
    npc_column: int = 6
    theme: str = "arena"
    width: int = 8
    height: int = 8


TEMPLATES: dict[str, MapTemplate] = {
    "arena": MapTemplate("arena", "Arène", (), theme="arena"),
    "tavern": MapTemplate(
        "tavern",
        "Taverne",
        (
            (0, 2),
            (0, 3),
            (0, 4),
            (3, 2),
            (4, 2),
            (3, 5),
            (4, 5),
        ),
        theme="tavern",
    ),
    "dungeon": MapTemplate(
        "dungeon",
        "Donjon",
        (
            (2, 2),
            (2, 3),
            (2, 4),
            (3, 4),
            (4, 5),
            (5, 3),
            (5, 4),
            (5, 5),
        ),
        theme="dungeon",
    ),
    "camp": MapTemplate(
        "camp",
        "Camp",
        (
            (1, 1),
            (3, 3),
            (4, 3),
            (3, 4),
            (4, 4),
            (6, 6),
        ),
        theme="camp",
    ),
}


def template_from_custom(data: CustomMapData) -> MapTemplate:
    return MapTemplate(
        map_id=data.map_id,
        label=data.label,
        blocked=data.blocked,
        pc_column=data.pc_column,
        npc_column=data.npc_column,
        theme=data.theme,
        width=data.width,
        height=data.height,
    )


def lookup_template(
    map_id: str | None, *, guild_id: int | None = None
) -> MapTemplate:
    key = (map_id or "arena").strip().lower()
    template = TEMPLATES.get(key)
    if template is not None:
        return template
    if guild_id is not None:
        custom = get_custom_map(guild_id=guild_id, map_id=key)
        if custom is not None:
            return template_from_custom(custom)
    known = ", ".join(sorted(known_map_ids(guild_id=guild_id)))
    raise ValueError(f"Carte inconnue `{map_id}`. Utilise : {known}.")


def known_map_ids(*, guild_id: int | None = None) -> set[str]:
    ids = set(TEMPLATES)
    if guild_id is not None:
        ids |= {entry.map_id for entry in list_custom_maps(guild_id=guild_id)}
    return ids


def template_for_state(state) -> MapTemplate:
    try:
        return lookup_template(state.map_id, guild_id=state.guild_id)
    except ValueError:
        blocked = tuple(
            (int(cell[0]), int(cell[1]))
            for cell in getattr(state, "blocked", [])
            if len(cell) >= 2
        )
        return MapTemplate(
            map_id=state.map_id or "arena",
            label=str(state.map_id or "Carte").replace("-", " ").title(),
            blocked=blocked,
            width=int(getattr(state, "map_width", 8) or 8),
            height=int(getattr(state, "map_height", 8) or 8),
        )
