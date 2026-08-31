from __future__ import annotations

import json
import re
from dataclasses import dataclass

from data.db import db_connection

COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
MIN_MAP_SIZE = 4
MAX_MAP_WIDTH = 16
MAX_MAP_HEIGHT = 16
DEFAULT_MAP_WIDTH = 8
DEFAULT_MAP_HEIGHT = 8
SIZE_RE = re.compile(r"^(\d+)\s*[x×]\s*(\d+)$", re.IGNORECASE)


def clamp_map_size(width: int, height: int) -> tuple[int, int]:
    if width < MIN_MAP_SIZE or height < MIN_MAP_SIZE:
        raise ValueError(f"Carte trop petite (minimum {MIN_MAP_SIZE}×{MIN_MAP_SIZE}).")
    if width > MAX_MAP_WIDTH or height > MAX_MAP_HEIGHT:
        raise ValueError(f"Carte trop grande (maximum {MAX_MAP_WIDTH}×{MAX_MAP_HEIGHT}).")
    return width, height


def parse_size_token(raw: str) -> tuple[int, int] | None:
    match = SIZE_RE.match(raw.strip())
    if match is None:
        return None
    return clamp_map_size(int(match.group(1)), int(match.group(2)))


def _in_bounds(x: int, y: int, width: int, height: int) -> bool:
    return 0 <= x < width and 0 <= y < height

THEMES = frozenset({"arena", "tavern", "dungeon", "camp"})
RESERVED_IDS = frozenset(
    {
        "new",
        "import",
        "export",
        "delete",
        "list",
        "save",
        "wall",
        "show",
        "remove",
        "help",
        "editor",
    }
)
MAP_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
HEADER_RE = re.compile(
    r"^#\s*(id|label|name|theme|pc|npc|size)\s*[:=]\s*(.+?)\s*$", re.IGNORECASE
)
CODEBLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", re.DOTALL)
MAX_MAP_BYTES = 32 * 1024


@dataclass(frozen=True)
class CustomMapData:
    map_id: str
    label: str
    blocked: tuple[tuple[int, int], ...]
    pc_column: int = 1
    npc_column: int = 6
    theme: str = "arena"
    width: int = DEFAULT_MAP_WIDTH
    height: int = DEFAULT_MAP_HEIGHT


def slugify_map_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower()).strip("-")
    return cleaned


def validate_map_id(map_id: str) -> str:
    key = slugify_map_id(map_id)
    if not MAP_ID_RE.match(key):
        raise ValueError(
            "Identifiant de carte invalide. Utilise `crypt` ou `salle-du-trone`."
        )
    if key in RESERVED_IDS:
        raise ValueError(f"`{key}` est réservé. Choisis un autre nom.")
    return key


def _column_from_token(raw: str, width: int) -> int:
    token = raw.strip()
    if token.isdigit():
        index = int(token) - 1
    elif len(token) == 1 and token.upper() in COLUMNS:
        index = COLUMNS.index(token.upper())
    else:
        raise ValueError(f"Colonne inconnue `{raw}`. Utilise A–{COLUMNS[width - 1]}.")
    if not 0 <= index < width:
        raise ValueError(f"Colonne hors carte `{raw}`.")
    return index


def _normalize_theme(raw: str | None) -> str:
    theme = (raw or "arena").strip().lower()
    if theme not in THEMES:
        known = ", ".join(sorted(THEMES))
        raise ValueError(f"Thème inconnu `{raw}`. Utilise : {known}.")
    return theme


def _blocked_from_grid(
    rows: list[str], *, width: int | None = None, height: int | None = None
) -> tuple[tuple[tuple[int, int], ...], int, int]:
    cleaned = [row.replace(" ", "") for row in rows if row.strip()]
    if not cleaned:
        raise ValueError("Aucune grille trouvée. `.` sol, `#` mur.")
    inferred_width = max(len(row) for row in cleaned)
    inferred_height = len(cleaned)
    width, height = clamp_map_size(
        width or max(inferred_width, MIN_MAP_SIZE),
        height or max(inferred_height, MIN_MAP_SIZE),
    )
    padded = list(cleaned[:height])
    while len(padded) < height:
        padded.append("." * width)
    blocked: list[tuple[int, int]] = []
    for y, raw in enumerate(padded):
        line = raw[:width].ljust(width, ".")
        for x, char in enumerate(line):
            if char in "#XxWw1":
                blocked.append((x, y))
    return tuple(blocked), width, height


def parse_map_text(text: str, *, default_id: str | None = None) -> CustomMapData:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if cleaned.startswith("{"):
        return parse_map_json(cleaned, default_id=default_id)
    headers: dict[str, str] = {}
    rows: list[str] = []
    for line in cleaned.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        header = HEADER_RE.match(stripped)
        if header is not None:
            headers[header.group(1).lower()] = header.group(2).strip()
            continue
        if re.fullmatch(r"[.#XxWw01_ ]{3,}", stripped):
            rows.append(stripped)
    if not rows:
        raise ValueError(
            "Aucune grille trouvée. `.` sol, `#` mur "
            f"(jusqu’à {MAX_MAP_WIDTH}×{MAX_MAP_HEIGHT})."
        )
    raw_id = headers.get("id") or default_id
    if not raw_id:
        raise ValueError("Ajoute `# id: crypt` ou un nom : `;combat map import crypt`.")
    label = headers.get("label") or headers.get("name") or raw_id.replace("-", " ").title()
    forced = parse_size_token(headers["size"]) if "size" in headers else None
    blocked, width, height = _blocked_from_grid(
        rows,
        width=forced[0] if forced else None,
        height=forced[1] if forced else None,
    )
    return CustomMapData(
        map_id=validate_map_id(raw_id),
        label=label[:80],
        blocked=blocked,
        pc_column=_column_from_token(headers["pc"], width) if "pc" in headers else 1,
        npc_column=(
            _column_from_token(headers["npc"], width)
            if "npc" in headers
            else max(1, width - 2)
        ),
        theme=_normalize_theme(headers.get("theme")),
        width=width,
        height=height,
    )


def parse_map_json(text: str, *, default_id: str | None = None) -> CustomMapData:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON invalide : {exc.msg}.") from exc
    if not isinstance(data, dict):
        raise ValueError("Le JSON de carte doit être un objet.")
    raw_id = data.get("id") or data.get("map_id") or default_id
    if not raw_id:
        raise ValueError("Le JSON doit avoir un champ `id`.")
    forced = None
    if data.get("size"):
        forced = parse_size_token(str(data["size"]))
    elif data.get("width") or data.get("height"):
        forced = clamp_map_size(
            int(data.get("width") or DEFAULT_MAP_WIDTH),
            int(data.get("height") or DEFAULT_MAP_HEIGHT),
        )
    if "grid" in data:
        grid = data["grid"]
        if not isinstance(grid, list) or not all(isinstance(row, str) for row in grid):
            raise ValueError("`grid` doit être une liste de lignes texte.")
        blocked, width, height = _blocked_from_grid(
            grid,
            width=forced[0] if forced else None,
            height=forced[1] if forced else None,
        )
    else:
        blocked = _blocked_from_pairs(
            data.get("blocked", []),
            width=forced[0] if forced else MAX_MAP_WIDTH,
            height=forced[1] if forced else MAX_MAP_HEIGHT,
        )
        if forced:
            width, height = forced
        elif blocked:
            width, height = clamp_map_size(
                max(cell[0] for cell in blocked) + 1,
                max(cell[1] for cell in blocked) + 1,
            )
        else:
            width, height = DEFAULT_MAP_WIDTH, DEFAULT_MAP_HEIGHT
    label = str(data.get("label") or data.get("name") or raw_id).strip()
    return CustomMapData(
        map_id=validate_map_id(str(raw_id)),
        label=(label or str(raw_id))[:80],
        blocked=blocked,
        pc_column=_column_from_token(
            str(data.get("pc") or data.get("pc_column") or "B"), width
        ),
        npc_column=_column_from_token(
            str(data.get("npc") or data.get("npc_column") or COLUMNS[max(0, width - 2)]),
            width,
        ),
        theme=_normalize_theme(str(data.get("theme") or "arena")),
        width=width,
        height=height,
    )


def _blocked_from_pairs(
    raw: object, *, width: int, height: int
) -> tuple[tuple[int, int], ...]:
    if not isinstance(raw, list):
        raise ValueError("`blocked` doit être une liste de coordonnées `[x, y]`.")
    cells: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, list | tuple) or len(item) < 2:
            raise ValueError("Chaque case bloquée doit être `[x, y]`.")
        x, y = int(item[0]), int(item[1])
        if not _in_bounds(x, y, width, height):
            raise ValueError(f"Case hors carte [{x}, {y}].")
        cells.append((x, y))
    return tuple(cells)


def extract_map_source(text: str) -> str | None:
    if not text.strip():
        return None
    match = CODEBLOCK_RE.search(text)
    if match is not None:
        return match.group(1).strip()
    stripped = text.strip()
    if stripped.startswith("{") or HEADER_RE.match(stripped.split("\n", 1)[0]):
        return stripped
    if re.search(r"[.#XxWw]{4,}", stripped):
        return stripped
    return None


def format_map_text(data: CustomMapData) -> str:
    blocked = set(data.blocked)
    lines = [
        f"# id: {data.map_id}",
        f"# label: {data.label}",
        f"# theme: {data.theme}",
        f"# size: {data.width}x{data.height}",
        f"# pc: {COLUMNS[data.pc_column]}",
        f"# npc: {COLUMNS[data.npc_column]}",
    ]
    for y in range(data.height):
        lines.append(
            "".join("#" if (x, y) in blocked else "." for x in range(data.width))
        )
    return "\n".join(lines) + "\n"


def custom_map_from_state(
    state,
    *,
    map_id: str,
    label: str | None = None,
    theme: str | None = None,
) -> CustomMapData:
    blocked = tuple(
        (int(cell[0]), int(cell[1]))
        for cell in state.blocked
        if len(cell) >= 2
        and _in_bounds(
            int(cell[0]),
            int(cell[1]),
            int(getattr(state, "map_width", DEFAULT_MAP_WIDTH) or DEFAULT_MAP_WIDTH),
            int(getattr(state, "map_height", DEFAULT_MAP_HEIGHT) or DEFAULT_MAP_HEIGHT),
        )
    )
    width = int(getattr(state, "map_width", DEFAULT_MAP_WIDTH) or DEFAULT_MAP_WIDTH)
    height = int(getattr(state, "map_height", DEFAULT_MAP_HEIGHT) or DEFAULT_MAP_HEIGHT)
    width, height = clamp_map_size(width, height)
    return CustomMapData(
        map_id=validate_map_id(map_id),
        label=(label or map_id.replace("-", " ").title())[:80],
        blocked=blocked,
        theme=_normalize_theme(theme or "arena"),
        width=width,
        height=height,
        npc_column=max(1, width - 2),
    )


def list_custom_maps(*, guild_id: int) -> list[CustomMapData]:
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT map_id, label, theme, blocked_json, pc_column, npc_column,
                   width, height
            FROM combat_maps
            WHERE guild_id = ?
            ORDER BY map_id
            """,
            (str(guild_id),),
        ).fetchall()
    return [_row_to_data(row) for row in rows]


def custom_map_ids(*, guild_id: int) -> set[str]:
    return {entry.map_id for entry in list_custom_maps(guild_id=guild_id)}


def get_custom_map(*, guild_id: int, map_id: str) -> CustomMapData | None:
    key = (map_id or "").strip().lower()
    if not key:
        return None
    with db_connection() as connection:
        row = connection.execute(
            """
            SELECT map_id, label, theme, blocked_json, pc_column, npc_column,
                   width, height
            FROM combat_maps
            WHERE guild_id = ? AND map_id = ?
            """,
            (str(guild_id), key),
        ).fetchone()
    if row is None:
        return None
    return _row_to_data(row)


def save_custom_map(*, guild_id: int, data: CustomMapData) -> None:
    payload = json.dumps([list(cell) for cell in data.blocked])
    with db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO combat_maps
                (guild_id, map_id, label, theme, blocked_json, pc_column, npc_column,
                 width, height)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(guild_id),
                data.map_id,
                data.label,
                data.theme,
                payload,
                data.pc_column,
                data.npc_column,
                data.width,
                data.height,
            ),
        )


def delete_custom_map(*, guild_id: int, map_id: str) -> bool:
    key = validate_map_id(map_id)
    with db_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM combat_maps WHERE guild_id = ? AND map_id = ?",
            (str(guild_id), key),
        )
    return cursor.rowcount > 0


def _row_to_data(row) -> CustomMapData:
    blocked = tuple(
        (int(cell[0]), int(cell[1]))
        for cell in json.loads(row["blocked_json"])
        if isinstance(cell, list) and len(cell) >= 2
    )
    keys = set(row.keys())
    width = int(row["width"]) if "width" in keys and row["width"] else DEFAULT_MAP_WIDTH
    height = (
        int(row["height"]) if "height" in keys and row["height"] else DEFAULT_MAP_HEIGHT
    )
    return CustomMapData(
        map_id=str(row["map_id"]),
        label=str(row["label"]),
        blocked=blocked,
        pc_column=int(row["pc_column"]),
        npc_column=int(row["npc_column"]),
        theme=str(row["theme"] or "arena"),
        width=width,
        height=height,
    )
