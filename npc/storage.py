from data.db import db_connection


def normalize_npc_name(name: str) -> str:
    return name.strip().title()


def register_npc_name(name: str) -> str:
    name = normalize_npc_name(name)
    if not name:
        return name
    with db_connection() as connection:
        connection.execute("DELETE FROM npc_names WHERE lower(name) = lower(?)", (name,))
        connection.execute("INSERT OR IGNORE INTO npc_names (name) VALUES (?)", (name,))
    return name


def get_npc_names() -> set[str]:
    with db_connection() as connection:
        rows = connection.execute("SELECT name FROM npc_names").fetchall()
    return {normalize_npc_name(row["name"]) for row in rows if row["name"].strip()}
