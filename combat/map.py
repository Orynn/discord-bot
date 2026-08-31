from __future__ import annotations

import re
from collections import deque

from combat.cards import WEAPON_CARD_ID, lookup_card
from combat.storage import CombatState, CombatantState
from combat.templates import lookup_template
from sheets.data import CharacterSheet

DEFAULT_MAP_WIDTH = 8
DEFAULT_MAP_HEIGHT = 8
MAX_MAP_WIDTH = 16
MAX_MAP_HEIGHT = 16
MAP_WIDTH = DEFAULT_MAP_WIDTH
MAP_HEIGHT = DEFAULT_MAP_HEIGHT
FEET_PER_SQUARE = 5
DEFAULT_SPEED_FT = 30
MELEE_RANGE = 1
PC_COLUMN = 1
NPC_COLUMN = MAP_WIDTH - 2
COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

CELL_RE = re.compile(r"^([A-Za-z])\s*([1-9][0-9]?)$")
STEP_RE = re.compile(
    r"^(?:(\d+)\s*)?(n|s|e|w|ne|nw|se|sw|north|south|east|west|"
    r"up|down|left|right|haut|bas|gauche|droite)$",
    re.IGNORECASE,
)

DIRECTION_DELTA: dict[str, tuple[int, int]] = {
    "n": (0, -1),
    "north": (0, -1),
    "up": (0, -1),
    "haut": (0, -1),
    "s": (0, 1),
    "south": (0, 1),
    "down": (0, 1),
    "bas": (0, 1),
    "e": (1, 0),
    "east": (1, 0),
    "right": (1, 0),
    "droite": (1, 0),
    "w": (-1, 0),
    "west": (-1, 0),
    "left": (-1, 0),
    "gauche": (-1, 0),
    "ne": (1, -1),
    "nw": (-1, -1),
    "se": (1, 1),
    "sw": (-1, 1),
}

STEP_NEIGHBORS = tuple(set(DIRECTION_DELTA.values()))


def map_width(state: CombatState | None = None) -> int:
    if state is None:
        return DEFAULT_MAP_WIDTH
    return max(1, min(MAX_MAP_WIDTH, int(getattr(state, "map_width", 0) or DEFAULT_MAP_WIDTH)))


def map_height(state: CombatState | None = None) -> int:
    if state is None:
        return DEFAULT_MAP_HEIGHT
    return max(
        1, min(MAX_MAP_HEIGHT, int(getattr(state, "map_height", 0) or DEFAULT_MAP_HEIGHT))
    )


def in_bounds(x: int, y: int, state: CombatState | None = None) -> bool:
    return 0 <= x < map_width(state) and 0 <= y < map_height(state)


def cell_label(
    x: int | None, y: int | None, state: CombatState | None = None
) -> str:
    if x is None or y is None or not in_bounds(x, y, state):
        return "?"
    if x >= len(COLUMNS):
        return "?"
    return f"{COLUMNS[x]}{y + 1}"


def parse_cell(
    text: str, state: CombatState | None = None
) -> tuple[int, int] | None:
    match = CELL_RE.match(text.strip())
    if match is None:
        return None
    letter = match.group(1).upper()
    if letter not in COLUMNS:
        return None
    x = COLUMNS.index(letter)
    y = int(match.group(2)) - 1
    if state is not None and not in_bounds(x, y, state):
        return None
    if state is None and not (0 <= x < MAX_MAP_WIDTH and 0 <= y < MAX_MAP_HEIGHT):
        return None
    return x, y


def chebyshev(ax: int, ay: int, bx: int, by: int) -> int:
    return max(abs(ax - bx), abs(ay - by))


def speed_squares(speed_ft: int) -> int:
    return max(0, int(speed_ft) // FEET_PER_SQUARE)


_NO_MOVE = frozenset(
    {
        "grappled",
        "restrained",
        "paralyzed",
        "stunned",
        "unconscious",
        "incapacitated",
    }
)


def movement_blockers(combatant: CombatantState) -> set[str]:
    return {str(key).lower() for key in combatant.conditions} & _NO_MOVE


def remaining_squares(combatant: CombatantState) -> int:
    if movement_blockers(combatant):
        return 0
    left = max(0, speed_squares(combatant.speed) - combatant.moved)
    keys = {str(key).lower() for key in combatant.conditions}
    if "prone" in keys:
        return left // 2
    return left


def speed_for_sheet(sheet: CharacterSheet | None) -> int:
    if sheet is None:
        return DEFAULT_SPEED_FT
    return max(0, int(sheet.effective_speed() or 0))


def is_eliminated(combatant: CombatantState) -> bool:
    if combatant.user_id is None:
        return combatant.hp <= 0
    return combatant.death_save_failures >= 3


def occupies_cell(combatant: CombatantState) -> bool:
    if combatant.x is None or combatant.y is None:
        return False
    return not is_eliminated(combatant)


def same_side(actor: CombatantState, other: CombatantState) -> bool:
    return (actor.user_id is None) == (other.user_id is None)


def is_wall(state: CombatState, x: int, y: int) -> bool:
    return (x, y) in state.blocked_set


def weapon_range_squares(combatant: CombatantState) -> int:
    card = lookup_card(combatant.card_catalog, WEAPON_CARD_ID)
    if card is None or card.range_squares is None:
        return MELEE_RANGE
    return max(0, int(card.range_squares))


def spawn_columns(state: CombatState) -> tuple[int, int]:
    template = lookup_template(state.map_id, guild_id=state.guild_id)
    return template.pc_column, template.npc_column


def occupant_at(
    state: CombatState, x: int, y: int, *, ignore: CombatantState | None = None
) -> CombatantState | None:
    for combatant in state.combatants.values():
        if combatant is ignore or not occupies_cell(combatant):
            continue
        if combatant.x == x and combatant.y == y:
            return combatant
    return None


def _blocks_path(
    state: CombatState, actor: CombatantState, x: int, y: int
) -> bool:
    if is_wall(state, x, y):
        return True
    other = occupant_at(state, x, y, ignore=actor)
    return other is not None


def path_length(
    state: CombatState,
    actor: CombatantState,
    dest_x: int,
    dest_y: int,
) -> int | None:
    if actor.x is None or actor.y is None:
        return None
    if not in_bounds(dest_x, dest_y, state):
        return None
    if actor.x == dest_x and actor.y == dest_y:
        return 0
    if is_wall(state, dest_x, dest_y):
        return None
    blocker = occupant_at(state, dest_x, dest_y, ignore=actor)
    if blocker is not None:
        return None

    start = (actor.x, actor.y)
    goal = (dest_x, dest_y)
    pending: deque[tuple[tuple[int, int], int]] = deque([(start, 0)])
    seen = {start}
    while pending:
        (x, y), dist = pending.popleft()
        for dx, dy in STEP_NEIGHBORS:
            nx, ny = x + dx, y + dy
            if (nx, ny) in seen or not in_bounds(nx, ny, state):
                continue
            if (nx, ny) != goal and _blocks_path(state, actor, nx, ny):
                continue
            if (nx, ny) == goal:
                return dist + 1
            seen.add((nx, ny))
            pending.append(((nx, ny), dist + 1))
    return None


def path_cells(
    state: CombatState,
    actor: CombatantState,
    dest_x: int,
    dest_y: int,
) -> list[tuple[int, int]] | None:
    if actor.x is None or actor.y is None:
        return None
    if actor.x == dest_x and actor.y == dest_y:
        return []
    if path_length(state, actor, dest_x, dest_y) is None:
        return None
    start = (actor.x, actor.y)
    goal = (dest_x, dest_y)
    pending: deque[tuple[int, int]] = deque([start])
    parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    while pending:
        x, y = pending.popleft()
        if (x, y) == goal:
            break
        for dx, dy in STEP_NEIGHBORS:
            nx, ny = x + dx, y + dy
            if (nx, ny) in parent or not in_bounds(nx, ny, state):
                continue
            if (nx, ny) != goal and _blocks_path(state, actor, nx, ny):
                continue
            if is_wall(state, nx, ny):
                continue
            parent[(nx, ny)] = (x, y)
            pending.append((nx, ny))
    if goal not in parent:
        return None
    cells: list[tuple[int, int]] = []
    cursor: tuple[int, int] | None = goal
    while cursor is not None and cursor != start:
        cells.append(cursor)
        cursor = parent.get(cursor)
    cells.reverse()
    return cells


def parse_destination(
    actor: CombatantState, text: str, state: CombatState | None = None
) -> tuple[int, int] | None:
    raw = text.strip()
    if not raw or actor.x is None or actor.y is None:
        return None
    cell = parse_cell(raw, state)
    if cell is not None:
        return cell
    match = STEP_RE.match(raw.replace(" ", ""))
    if match is None:
        return None
    steps = int(match.group(1) or 1)
    delta = DIRECTION_DELTA[match.group(2).lower()]
    dest = (actor.x + delta[0] * steps, actor.y + delta[1] * steps)
    return dest


def _first_empty_column(state: CombatState, column: int) -> tuple[int, int] | None:
    for y in range(map_height(state)):
        if occupant_at(state, column, y) is None and not is_wall(state, column, y):
            return column, y
    return None


def _first_empty_cell(state: CombatState) -> tuple[int, int] | None:
    for y in range(map_height(state)):
        for x in range(map_width(state)):
            if occupant_at(state, x, y) is None and not is_wall(state, x, y):
                return x, y
    return None


def place_new_combatant(state: CombatState, combatant: CombatantState) -> None:
    pc_column, npc_column = spawn_columns(state)
    column = pc_column if combatant.user_id is not None else npc_column
    cell = _first_empty_column(state, column) or _first_empty_cell(state)
    if cell is None:
        combatant.x = 0
        combatant.y = 0
        return
    combatant.x, combatant.y = cell


def _layout_sides(state: CombatState) -> None:
    pcs = [
        state.combatants[name.lower()]
        for name in state.turn_order
        if name.lower() in state.combatants
        and state.combatants[name.lower()].user_id is not None
    ]
    npcs = [
        state.combatants[name.lower()]
        for name in state.turn_order
        if name.lower() in state.combatants
        and state.combatants[name.lower()].user_id is None
    ]
    extras = [
        combatant
        for combatant in state.combatants.values()
        if combatant not in pcs and combatant not in npcs
    ]

    def _spread(group: list[CombatantState], column: int) -> None:
        if not group:
            return
        y = max(0, (map_height(state) - len(group)) // 2)
        for combatant in group:
            while y < map_height(state) and (
                is_wall(state, column, y) or occupant_at(state, column, y)
            ):
                y += 1
            if y >= map_height(state):
                place_new_combatant(state, combatant)
                continue
            combatant.x = column
            combatant.y = y
            y += 1

    pc_column, npc_column = spawn_columns(state)
    if pcs and npcs:
        _spread(pcs, pc_column)
        _spread(npcs, npc_column)
    elif pcs:
        _spread(pcs, pc_column)
    else:
        _spread(npcs, npc_column)
    for combatant in extras:
        place_new_combatant(state, combatant)


def ensure_positions(state: CombatState) -> None:
    missing = [
        combatant
        for combatant in state.combatants.values()
        if combatant.x is None or combatant.y is None
    ]
    if not missing:
        return
    placed = any(
        combatant.x is not None and combatant.y is not None
        for combatant in state.combatants.values()
    )
    if not placed:
        _layout_sides(state)
        return
    for combatant in missing:
        place_new_combatant(state, combatant)


def distance_squares(actor: CombatantState, other: CombatantState) -> int | None:
    if actor.x is None or actor.y is None or other.x is None or other.y is None:
        return None
    return chebyshev(actor.x, actor.y, other.x, other.y)


def in_range(
    actor: CombatantState, other: CombatantState, range_squares: int | None
) -> bool:
    if range_squares is None:
        return True
    if other is actor or (
        other.name.lower() == actor.name.lower() and other.user_id == actor.user_id
    ):
        return True
    distance = distance_squares(actor, other)
    if distance is None:
        return False
    return distance <= range_squares


def combatants_in_range(
    state: CombatState,
    actor: CombatantState,
    range_squares: int,
    *,
    enemies_only: bool = False,
) -> list[CombatantState]:
    if actor.x is None or actor.y is None:
        return []
    found: list[CombatantState] = []
    for combatant in state.combatants.values():
        if combatant is actor or not occupies_cell(combatant):
            continue
        if enemies_only and same_side(actor, combatant):
            continue
        if in_range(actor, combatant, range_squares):
            found.append(combatant)
    return found


def targets_in_range(
    state: CombatState, actor: CombatantState, range_squares: int
) -> list[CombatantState]:
    return combatants_in_range(state, actor, range_squares, enemies_only=True)


def attack_targets_in_range(
    state: CombatState, actor: CombatantState, range_squares: int
) -> list[CombatantState]:
    return combatants_in_range(state, actor, range_squares, enemies_only=False)


def melee_targets(state: CombatState, actor: CombatantState) -> list[CombatantState]:
    return targets_in_range(state, actor, MELEE_RANGE)


def reachable_cells(
    state: CombatState, actor: CombatantState
) -> set[tuple[int, int]]:
    budget = remaining_squares(actor)
    found: set[tuple[int, int]] = set()
    if actor.x is None or actor.y is None or budget <= 0:
        return found
    for x in range(map_width(state)):
        for y in range(map_height(state)):
            cost = path_length(state, actor, x, y)
            if cost is not None and 0 < cost <= budget:
                found.add((x, y))
    return found


def best_move_toward(
    state: CombatState,
    actor: CombatantState,
    target: CombatantState,
    *,
    keep_distance: bool = False,
) -> tuple[int, int] | None:
    if actor.x is None or actor.y is None or target.x is None or target.y is None:
        return None
    budget = remaining_squares(actor)
    reach = max(1, weapon_range_squares(actor))
    best: tuple[int, int] | None = None
    best_score: tuple[int, int, int, int] | None = None
    for x in range(map_width(state)):
        for y in range(map_height(state)):
            cost = path_length(state, actor, x, y)
            if cost is None or cost > budget:
                continue
            dist = chebyshev(x, y, target.x, target.y)
            in_reach = 0 if dist <= reach else 1
            melee = 1 if keep_distance and dist <= MELEE_RANGE else 0
            ideal = abs(dist - reach) if keep_distance else dist
            score = (in_reach, melee, ideal, cost)
            if best_score is None or score < best_score:
                best = (x, y)
                best_score = score
    return best


def cells_in_radius(
    cx: int, cy: int, radius: int, state: CombatState | None = None
) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    for x in range(map_width(state)):
        for y in range(map_height(state)):
            if chebyshev(cx, cy, x, y) <= radius:
                found.append((x, y))
    return found


def combatants_in_radius(
    state: CombatState,
    cx: int,
    cy: int,
    radius: int,
) -> list[CombatantState]:
    cells = set(cells_in_radius(cx, cy, radius, state))
    found: list[CombatantState] = []
    for combatant in state.combatants.values():
        if not occupies_cell(combatant):
            continue
        if combatant.x is None or combatant.y is None:
            continue
        if (combatant.x, combatant.y) in cells:
            found.append(combatant)
    return found


def apply_template(state: CombatState, map_id: str | None) -> None:
    template = lookup_template(map_id, guild_id=state.guild_id)
    state.map_id = template.map_id
    state.map_width = template.width
    state.map_height = template.height
    state.blocked = [list(cell) for cell in template.blocked]
    for combatant in state.combatants.values():
        combatant.x = None
        combatant.y = None
    ensure_positions(state)


def toggle_walls(state: CombatState, cells: list[tuple[int, int]]) -> str:
    blocked = state.blocked_set
    added: list[str] = []
    removed: list[str] = []
    skipped: list[str] = []
    for x, y in cells:
        if not in_bounds(x, y, state):
            continue
        label = cell_label(x, y, state)
        if occupant_at(state, x, y) is not None and (x, y) not in blocked:
            skipped.append(label)
            continue
        if (x, y) in blocked:
            blocked.remove((x, y))
            removed.append(label)
        else:
            blocked.add((x, y))
            added.append(label)
    state.blocked = [list(cell) for cell in sorted(blocked)]
    parts: list[str] = []
    if added:
        parts.append(f"murs +{' '.join(added)}")
    if removed:
        parts.append(f"murs −{' '.join(removed)}")
    if skipped:
        parts.append(f"occupées {', '.join(skipped)}")
    if not parts:
        raise ValueError("Aucune case à modifier. Exemple : `;combat map wall C3 D4`.")
    return " · ".join(parts)
