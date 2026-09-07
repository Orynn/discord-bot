from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from combat.storage import CombatState, clear_combat
from combat.templates import lookup_template
from combat.text import format_log_line
from config import PREFIX
from data.db import db_connection

_DEFAULT_LIST_LIMIT = 10


@dataclass(frozen=True)
class CombatArchive:
    id: int
    guild_id: int
    scope_id: int
    ended_at: datetime
    map_id: str
    winner: str | None
    combatants: list[dict]
    log: list[str]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ended_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _combatants_payload(state: CombatState) -> list[dict]:
    rows: list[dict] = []
    for name in state.turn_order:
        combatant = state.combatants.get(name.lower())
        if combatant is None:
            continue
        rows.append(
            {
                "name": combatant.name,
                "hp": combatant.hp,
                "max_hp": combatant.max_hp,
                "pc": combatant.user_id is not None,
            }
        )
    return rows


def archive_combat(state: CombatState, *, winner: str | None = None) -> int:
    payload = json.dumps(_combatants_payload(state), ensure_ascii=False)
    log_payload = json.dumps(list(state.log), ensure_ascii=False)
    ended_at = _utc_now().isoformat()
    with db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO combat_history (
                guild_id, scope_id, ended_at, map_id, winner,
                combatants_json, log_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(state.guild_id),
                str(state.scope_id),
                ended_at,
                state.map_id,
                winner,
                payload,
                log_payload,
            ),
        )
        return int(cursor.lastrowid)


def finish_combat(state: CombatState, *, winner: str | None = None) -> int | None:
    archive_id = archive_combat(state, winner=winner)
    clear_combat(guild_id=state.guild_id, scope_id=state.scope_id)
    return archive_id


def list_combat_history(
    *, guild_id: int, scope_id: int, limit: int = _DEFAULT_LIST_LIMIT
) -> list[CombatArchive]:
    capped = max(1, min(int(limit), 50))
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, guild_id, scope_id, ended_at, map_id, winner,
                   combatants_json, log_json
            FROM combat_history
            WHERE guild_id = ? AND scope_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (str(guild_id), str(scope_id), capped),
        ).fetchall()
    return [_row_to_archive(row) for row in rows]


def get_combat_archive(
    *, guild_id: int, scope_id: int, archive_id: int
) -> CombatArchive | None:
    with db_connection() as connection:
        row = connection.execute(
            """
            SELECT id, guild_id, scope_id, ended_at, map_id, winner,
                   combatants_json, log_json
            FROM combat_history
            WHERE guild_id = ? AND scope_id = ? AND id = ?
            """,
            (str(guild_id), str(scope_id), int(archive_id)),
        ).fetchone()
    if row is None:
        return None
    return _row_to_archive(row)


def latest_combat_archive(*, guild_id: int, scope_id: int) -> CombatArchive | None:
    entries = list_combat_history(guild_id=guild_id, scope_id=scope_id, limit=1)
    return entries[0] if entries else None


def _row_to_archive(row) -> CombatArchive:
    return CombatArchive(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        scope_id=int(row["scope_id"]),
        ended_at=_parse_ended_at(str(row["ended_at"])),
        map_id=str(row["map_id"] or "arena"),
        winner=row["winner"],
        combatants=json.loads(row["combatants_json"]),
        log=json.loads(row["log_json"]),
    )


def format_winner_label(winner: str | None) -> str:
    if not winner:
        return "—"
    if winner == "the party":
        return "le groupe"
    if winner == "the monsters":
        return "les monstres"
    return winner


def format_archive_when(ended_at: datetime) -> str:
    stamp = ended_at.astimezone(timezone.utc)
    return stamp.strftime("%d/%m/%Y %H:%M UTC")


def _map_label(map_id: str) -> str:
    return lookup_template(map_id).label


def _combatants_line(combatants: list[dict]) -> str:
    parts: list[str] = []
    for entry in combatants:
        name = str(entry.get("name") or "?")
        if entry.get("pc"):
            hp = int(entry.get("hp") or 0)
            max_hp = int(entry.get("max_hp") or 0)
            parts.append(f"**{name}** {hp}/{max_hp}")
        else:
            hp = int(entry.get("hp") or 0)
            parts.append(f"**{name}**{' 💀' if hp <= 0 else ''}")
    return " · ".join(parts) if parts else "*(aucun combattant)*"


def format_history_list(
    entries: list[CombatArchive], *, limit: int = _DEFAULT_LIST_LIMIT
) -> str:
    if not entries:
        return "Aucun combat archivé pour cette section."
    lines = ["**Historique de combat**"]
    for entry in entries:
        winner = format_winner_label(entry.winner)
        when = format_archive_when(entry.ended_at)
        map_label = _map_label(entry.map_id)
        lines.append(f"`#{entry.id}` · {when} · {map_label} · vainqueur : {winner}")
    lines.append(
        f"\n`{PREFIX}combat historique <id>` ou `{PREFIX}combat historique dernier` pour le détail."
    )
    return "\n".join(lines)


def format_history_detail(entry: CombatArchive) -> str:
    when = format_archive_when(entry.ended_at)
    map_label = _map_label(entry.map_id)
    winner = format_winner_label(entry.winner)
    lines = [
        f"**Combat #{entry.id}** — {when}",
        f"Carte : **{map_label}** · Vainqueur : **{winner}**",
        _combatants_line(entry.combatants),
        "",
        "**Actions**",
    ]
    if entry.log:
        lines.extend(format_log_line(line) for line in entry.log)
    else:
        lines.append("*(aucune action enregistrée)*")
    return "\n".join(lines)
