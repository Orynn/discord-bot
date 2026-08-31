import asyncio
import json
from dataclasses import dataclass, field

from combat.cards import CardSnapshot
from data.db import db_connection


def _blocked_cells(value: object) -> list[list[int]]:
    if not isinstance(value, list):
        return []
    cells: list[list[int]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            cells.append([int(item[0]), int(item[1])])
    return cells


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


@dataclass
class CombatantState:
    name: str
    user_id: int | None
    hp: int
    max_hp: int
    hand: list[str]
    deck: list[str]
    discard: list[str] = field(default_factory=list)
    card_catalog: dict[str, CardSnapshot] = field(default_factory=dict)
    effects: list[str] = field(default_factory=list)
    traits: list[str] = field(default_factory=list)
    ac: int = 10
    attack_bonus: int = 4
    death_save_successes: int = 0
    death_save_failures: int = 0
    conditions: list[str] = field(default_factory=list)
    x: int | None = None
    y: int | None = None
    speed: int = 30
    moved: int = 0
    acted: bool = False
    concentrating: str = ""
    attacks: int = 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "user_id": self.user_id,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "hand": self.hand,
            "deck": self.deck,
            "discard": self.discard,
            "card_catalog": {
                key: card.to_dict() for key, card in self.card_catalog.items()
            },
            "effects": self.effects,
            "traits": self.traits,
            "ac": self.ac,
            "attack_bonus": self.attack_bonus,
            "death_save_successes": self.death_save_successes,
            "death_save_failures": self.death_save_failures,
            "conditions": self.conditions,
            "x": self.x,
            "y": self.y,
            "speed": self.speed,
            "moved": self.moved,
            "acted": self.acted,
            "concentrating": self.concentrating,
            "attacks": self.attacks,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CombatantState":
        catalog = {
            key: CardSnapshot.from_dict(value)
            for key, value in data.get("card_catalog", {}).items()
        }
        return cls(
            name=data["name"],
            user_id=data.get("user_id"),
            hp=int(data["hp"]),
            max_hp=int(data["max_hp"]),
            hand=list(data.get("hand", [])),
            deck=list(data.get("deck", [])),
            discard=list(data.get("discard", [])),
            card_catalog=catalog,
            effects=list(data.get("effects", [])),
            traits=list(data.get("traits", [])),
            ac=int(data.get("ac", 10)),
            attack_bonus=int(data.get("attack_bonus", 4)),
            death_save_successes=int(data.get("death_save_successes", 0)),
            death_save_failures=int(data.get("death_save_failures", 0)),
            conditions=list(data.get("conditions", [])),
            x=_optional_int(data.get("x")),
            y=_optional_int(data.get("y")),
            speed=int(data.get("speed", 30)),
            moved=int(data.get("moved", 0)),
            acted=bool(data.get("acted", False)),
            concentrating=str(data.get("concentrating") or ""),
            attacks=max(1, int(data.get("attacks") or 1)),
        )


@dataclass
class CombatState:
    guild_id: int
    channel_id: int
    turn_order: list[str]
    active_index: int
    combatants: dict[str, CombatantState]
    log: list[str] = field(default_factory=list)
    scope_id: int = 0
    map_id: str = "arena"
    map_width: int = 8
    map_height: int = 8
    blocked: list[list[int]] = field(default_factory=list)
    board_message_id: int | None = None

    def to_dict(self) -> dict:
        return {
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "scope_id": self.scope_id,
            "turn_order": self.turn_order,
            "active_index": self.active_index,
            "combatants": {
                key: combatant.to_dict() for key, combatant in self.combatants.items()
            },
            "log": self.log,
            "map_id": self.map_id,
            "map_width": self.map_width,
            "map_height": self.map_height,
            "blocked": self.blocked,
            "board_message_id": self.board_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CombatState":
        combatants = {
            key: CombatantState.from_dict(value)
            for key, value in data.get("combatants", {}).items()
        }
        return cls(
            guild_id=int(data["guild_id"]),
            channel_id=int(data["channel_id"]),
            scope_id=int(data.get("scope_id") or 0),
            turn_order=list(data.get("turn_order", [])),
            active_index=int(data.get("active_index", 0)),
            combatants=combatants,
            log=list(data.get("log", [])),
            map_id=str(data.get("map_id") or "arena"),
            map_width=int(data.get("map_width") or 8),
            map_height=int(data.get("map_height") or 8),
            blocked=_blocked_cells(data.get("blocked")),
            board_message_id=_optional_int(data.get("board_message_id")),
        )

    @property
    def blocked_set(self) -> set[tuple[int, int]]:
        return {(int(cell[0]), int(cell[1])) for cell in self.blocked if len(cell) >= 2}

    @property
    def active_name(self) -> str | None:
        if not self.turn_order:
            return None
        if not 0 <= self.active_index < len(self.turn_order):
            return None
        return self.turn_order[self.active_index]

    def active_combatant(self) -> CombatantState | None:
        name = self.active_name
        if name is None:
            return None
        return self.combatants.get(name.lower())

    def find_combatant(self, query: str) -> CombatantState | None:
        normalized = query.strip().lower()
        if not normalized:
            return None
        if normalized in self.combatants:
            return self.combatants[normalized]
        matches = [
            combatant
            for key, combatant in self.combatants.items()
            if normalized in key or normalized in combatant.name.lower()
        ]
        if len(matches) == 1:
            return matches[0]
        return None


def get_combat(*, guild_id: int, scope_id: int) -> CombatState | None:
    with db_connection() as connection:
        row = connection.execute(
            "SELECT state_json FROM combat WHERE guild_id = ? AND scope_id = ?",
            (str(guild_id), str(scope_id)),
        ).fetchone()
    if row is None:
        return None
    return CombatState.from_dict(json.loads(row["state_json"]))


def save_combat(state: CombatState) -> None:
    payload = json.dumps(state.to_dict(), ensure_ascii=False)
    with db_connection() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO combat (guild_id, scope_id, state_json)
            VALUES (?, ?, ?)
            """,
            (str(state.guild_id), str(state.scope_id), payload),
        )


async def set_board_message(
    *,
    guild_id: int,
    scope_id: int,
    message_id: int | None,
    channel_id: int | None = None,
) -> None:
    """Update only the Discord board pointer. Reloads under the combat lock."""
    async with lock_for(guild_id=guild_id, scope_id=scope_id):
        state = get_combat(guild_id=guild_id, scope_id=scope_id)
        if state is None:
            return
        state.board_message_id = message_id
        if channel_id is not None:
            state.channel_id = channel_id
        save_combat(state)


def clear_combat(*, guild_id: int, scope_id: int | None = None) -> None:
    with db_connection() as connection:
        if scope_id is None:
            connection.execute(
                "DELETE FROM combat WHERE guild_id = ?", (str(guild_id),)
            )
            return
        connection.execute(
            "DELETE FROM combat WHERE guild_id = ? AND scope_id = ?",
            (str(guild_id), str(scope_id)),
        )


_locks: dict[tuple[int, int], asyncio.Lock] = {}


def lock_for(*, guild_id: int, scope_id: int) -> asyncio.Lock:
    key = (int(guild_id), int(scope_id))
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock
