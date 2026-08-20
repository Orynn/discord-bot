from data.db import db_connection


def normalize_npc_name(name: str) -> str:
    return name.strip().title()


def register_npc_name(*, guild_id: int, name: str) -> str:
    name = normalize_npc_name(name)
    if not name:
        return name
    with db_connection() as connection:
        connection.execute(
            "DELETE FROM npc_names WHERE guild_id = ? AND lower(name) = lower(?)",
            (str(guild_id), name),
        )
        connection.execute(
            "INSERT OR IGNORE INTO npc_names (guild_id, name) VALUES (?, ?)",
            (str(guild_id), name),
        )
    return name


def get_npc_names(*, guild_id: int) -> set[str]:
    with db_connection() as connection:
        rows = connection.execute(
            "SELECT name FROM npc_names WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchall()
    return {normalize_npc_name(row["name"]) for row in rows if row["name"].strip()}
