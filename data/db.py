import json
import sqlite3
import threading
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from data import DATA_DIR

DB_FILE = DATA_DIR / "arkann.db"
_LEGACY_DB_FILE = DATA_DIR / "arkan.db"
_thread_local = threading.local()


def _migrate_db_file() -> None:
    if DB_FILE.exists() or not _LEGACY_DB_FILE.exists():
        return
    _LEGACY_DB_FILE.rename(DB_FILE)
    for suffix in ("-wal", "-shm"):
        legacy = Path(f"{_LEGACY_DB_FILE}{suffix}")
        if legacy.exists():
            legacy.rename(Path(f"{DB_FILE}{suffix}"))


def _connect() -> sqlite3.Connection:
    connection = getattr(_thread_local, "connection", None)
    path = getattr(_thread_local, "path", None)
    db_path = str(DB_FILE)
    if connection is not None and path == db_path:
        return connection
    if connection is not None:
        connection.close()
    connection = sqlite3.connect(DB_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    _thread_local.connection = connection
    _thread_local.path = db_path
    return connection


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def init_db() -> None:
    _migrate_db_file()
    with db_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sheets (
                user_id TEXT NOT NULL,
                guild_id TEXT NOT NULL,
                data TEXT NOT NULL,
                PRIMARY KEY (user_id, guild_id)
            );
            CREATE TABLE IF NOT EXISTS npc_names (
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                PRIMARY KEY (guild_id, name)
            );
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS party_treasury (
                guild_id TEXT PRIMARY KEY,
                currency TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS initiative (
                guild_id TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                active_index INTEGER NOT NULL DEFAULT 0,
                order_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, scope_id)
            );
            CREATE TABLE IF NOT EXISTS combat (
                guild_id TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, scope_id)
            );
            CREATE TABLE IF NOT EXISTS stashed_gear (
                guild_id TEXT NOT NULL,
                place_key TEXT NOT NULL,
                place_name TEXT NOT NULL,
                items_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, place_key)
            );
            """
        )
    _migrate_guild_scoped_tables()
    _migrate_json_files()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _legacy_guild_id() -> str:
    from config import CAMPAIGN_GUILD_ID

    return str(CAMPAIGN_GUILD_ID) if CAMPAIGN_GUILD_ID is not None else "0"


def _migrate_guild_scoped_tables() -> None:
    with db_connection() as connection:
        _migrate_sheets_guild(connection)
        _migrate_npc_names_guild(connection)
        _migrate_player_scoped_combat(connection)


def _migrate_sheets_guild(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "sheets")
    if not columns or "guild_id" in columns:
        return
    default_guild = _legacy_guild_id()
    connection.execute(
        """
        CREATE TABLE sheets_v2 (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (user_id, guild_id)
        )
        """
    )
    connection.execute(
        "INSERT INTO sheets_v2 (user_id, guild_id, data) SELECT user_id, ?, data FROM sheets",
        (default_guild,),
    )
    connection.execute("DROP TABLE sheets")
    connection.execute("ALTER TABLE sheets_v2 RENAME TO sheets")


def _migrate_npc_names_guild(connection: sqlite3.Connection) -> None:
    columns = _table_columns(connection, "npc_names")
    if not columns or "guild_id" in columns:
        return
    default_guild = _legacy_guild_id()
    connection.execute(
        """
        CREATE TABLE npc_names_v2 (
            guild_id TEXT NOT NULL,
            name TEXT NOT NULL,
            PRIMARY KEY (guild_id, name)
        )
        """
    )
    connection.execute(
        "INSERT OR IGNORE INTO npc_names_v2 (guild_id, name) SELECT ?, name FROM npc_names",
        (default_guild,),
    )
    connection.execute("DROP TABLE npc_names")
    connection.execute("ALTER TABLE npc_names_v2 RENAME TO npc_names")


def _migrate_player_scoped_combat(connection: sqlite3.Connection) -> None:
    combat_cols = _table_columns(connection, "combat")
    if combat_cols and "scope_id" not in combat_cols:
        connection.execute("DROP TABLE combat")
        connection.execute(
            """
            CREATE TABLE combat (
                guild_id TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, scope_id)
            )
            """
        )
    initiative_cols = _table_columns(connection, "initiative")
    if initiative_cols and "scope_id" not in initiative_cols:
        connection.execute("DROP TABLE initiative")
        connection.execute(
            """
            CREATE TABLE initiative (
                guild_id TEXT NOT NULL,
                scope_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                active_index INTEGER NOT NULL DEFAULT 0,
                order_json TEXT NOT NULL,
                PRIMARY KEY (guild_id, scope_id)
            )
            """
        )


def _migrate_json_files() -> None:
    sheets_file = DATA_DIR / "sheets.json"
    pc_file = DATA_DIR / "pc.json"
    npc_file = DATA_DIR / "npc.json"
    state_file = DATA_DIR / "bot_state.json"

    with db_connection() as connection:
        if (
            sheets_file.exists()
            and connection.execute("SELECT COUNT(*) FROM sheets").fetchone()[0] == 0
        ):
            sheets = json.loads(sheets_file.read_text(encoding="utf-8"))
            for user_id, data in sheets.items():
                connection.execute(
                    "INSERT OR REPLACE INTO sheets (user_id, guild_id, data) VALUES (?, ?, ?)",
                    (user_id, _legacy_guild_id(), json.dumps(data, ensure_ascii=False)),
                )

        if pc_file.exists():
            pcs = json.loads(pc_file.read_text(encoding="utf-8"))
            for user_id, name in pcs.items():
                row = connection.execute(
                    "SELECT data FROM sheets WHERE user_id = ? AND guild_id = ?",
                    (user_id, _legacy_guild_id()),
                ).fetchone()
                if row is None and name:
                    from sheets.data import CharacterSheet

                    sheet = CharacterSheet(name=name)
                    connection.execute(
                        "INSERT OR REPLACE INTO sheets (user_id, guild_id, data) VALUES (?, ?, ?)",
                        (
                            user_id,
                            _legacy_guild_id(),
                            json.dumps(sheet.to_dict(), ensure_ascii=False),
                        ),
                    )

        if (
            npc_file.exists()
            and connection.execute("SELECT COUNT(*) FROM npc_names").fetchone()[0] == 0
        ):
            names = json.loads(npc_file.read_text(encoding="utf-8"))
            for name in names:
                connection.execute(
                    "INSERT OR IGNORE INTO npc_names (guild_id, name) VALUES (?, ?)",
                    (_legacy_guild_id(), name),
                )

        if state_file.exists():
            row = connection.execute(
                "SELECT value FROM kv_store WHERE key = ?",
                ("last_message_ids",),
            ).fetchone()
            if row is None:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if "last_message_ids" in state:
                    connection.execute(
                        "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
                        (
                            "last_message_ids",
                            json.dumps(state["last_message_ids"], ensure_ascii=False),
                        ),
                    )


def get_json(key: str) -> Any | None:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["value"])


def set_json(key: str, value: Any) -> None:
    with db_connection() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )


def update_json(key: str, default: Any, updater: Callable[[Any], Any]) -> Any:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT value FROM kv_store WHERE key = ?", (key,)
        ).fetchone()
        current = json.loads(row["value"]) if row is not None else default
        updated = updater(current)
        connection.execute(
            "INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)",
            (key, json.dumps(updated, ensure_ascii=False)),
        )
        return updated


def mark_channel_message_processed(*, channel_id: int, message_id: int) -> None:
    def _update(last_ids: dict[str, int]) -> dict[str, int]:
        updated = dict(last_ids)
        current = updated.get(str(channel_id), 0)
        if message_id > current:
            updated[str(channel_id)] = message_id
        return updated

    update_json("last_message_ids", {}, _update)
