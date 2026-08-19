import json
from dataclasses import dataclass

from data.db import db_connection


@dataclass
class InitiativeEntry:
    name: str
    total: int
    user_id: int | None = None

    @classmethod
    def from_storage(cls, data: dict) -> "InitiativeEntry":
        total = data.get("total", data.get("modifier", 0))
        return cls(name=data["name"], total=int(total), user_id=data.get("user_id"))


@dataclass
class InitiativeState:
    channel_id: int
    active_index: int
    order: list[InitiativeEntry]


def get_initiative(guild_id: int) -> InitiativeState | None:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT channel_id, active_index, order_json FROM initiative WHERE guild_id = ?",
            (str(guild_id),),
        ).fetchone()
    if row is None:
        return None
    order = [InitiativeEntry.from_storage(item) for item in json.loads(row["order_json"])]
    return InitiativeState(
        channel_id=int(row["channel_id"]),
        active_index=row["active_index"],
        order=order,
    )


def save_initiative(guild_id: int, state: InitiativeState) -> None:
    payload = json.dumps(
        [{"name": entry.name, "total": entry.total, "user_id": entry.user_id} for entry in state.order],
        ensure_ascii=False,
    )
    with db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO initiative (guild_id, channel_id, active_index, order_json)
            VALUES (?, ?, ?, ?)
            """,
            (str(guild_id), str(state.channel_id), state.active_index, payload),
        )


def clear_initiative(guild_id: int) -> None:
    with db_connection() as connection:
        connection.execute("DELETE FROM initiative WHERE guild_id = ?", (str(guild_id),))
