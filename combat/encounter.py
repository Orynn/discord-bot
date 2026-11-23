"""Encounter state: who fights, in which order, with what HP and conditions.

Pure data and rules, no Discord. Player HP lives on their character sheet;
monster HP lives here.
"""

import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from data.db import delete_json, get_json, set_json
from sheets.conditions import normalize_condition
from sheets.data import fold_lookup_key

MONSTER = "monster"
PLAYER = "player"

CONDITION_LABELS: dict[str, str] = {
    "poisoned": "🤢 empoisonné",
    "frightened": "😱 effrayé",
    "blinded": "🙈 aveuglé",
    "restrained": "⛓️ entravé",
    "prone": "🛌 à terre",
    "paralyzed": "⚡ paralysé",
    "unconscious": "💤 inconscient",
    "stunned": "💫 étourdi",
    "incapacitated": "🚫 neutralisé",
    "grappled": "🤼 agrippé",
    "blessed": "🙏 béni",
    "baned": "🪦 fléau",
    "exhaustion": "😩 épuisé",
}

_NUMBERED_NAME = re.compile(r"^(.*?)\s+(\d+)$")


def condition_key(text: str) -> str:
    """Canonical key for a condition: `à terre` → `prone`, free text kept as is."""
    cleaned = " ".join(text.lower().split())
    return normalize_condition(cleaned) or cleaned


def condition_label(key: str) -> str:
    return CONDITION_LABELS.get(key, key)


@dataclass
class Combatant:
    id: str
    name: str
    kind: str
    initiative: int
    init_bonus: int = 0
    tiebreak: float = field(default_factory=random.random)
    hp: int = 0
    hp_max: int = 0
    ac: int | None = None
    user_id: int | None = None
    source: str = ""
    # Condition key → rounds left (counted on this creature's turns), None = no limit.
    conditions: dict[str, int | None] = field(default_factory=dict)
    # Conditions set during this creature's own turn: they start counting on its
    # next turn, so `à terre 1` lasts until the end of that next turn.
    fresh_conditions: list[str] = field(default_factory=list)
    temp_hp: int = 0
    dead: bool = False
    # Monster attacks (`combat.attacks.Attack` as dicts) and damage defenses.
    attacks: list[dict[str, Any]] = field(default_factory=list)
    resist: list[str] = field(default_factory=list)
    immune: list[str] = field(default_factory=list)
    vulnerable: list[str] = field(default_factory=list)
    # Saving throw bonuses (monsters; players read their sheet).
    saves: dict[str, int] = field(default_factory=dict)
    # Monster actions with a saving throw (breath weapons), as `SpellInfo` dicts.
    save_actions: list[dict[str, Any]] = field(default_factory=list)
    spell_dc: int | None = None
    spell_attack: int | None = None
    # {"spell": name, "links": [[combatant id, condition key], …]}
    concentration: dict[str, Any] | None = None
    reaction_used: bool = False

    @property
    def is_player(self) -> bool:
        return self.kind == PLAYER

    @property
    def is_out(self) -> bool:
        """A monster at 0 HP or a dead player leaves the turn order.

        A player at 0 HP keeps their turn for death saves.
        """
        return self.dead or (not self.is_player and self.hp <= 0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Combatant":
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})


def monster_state(combatant: Combatant) -> str:
    if combatant.dead or combatant.hp <= 0:
        return "💀 hors combat"
    if combatant.hp >= combatant.hp_max:
        return "indemne"
    if combatant.hp * 2 > combatant.hp_max:
        return "🩹 blessé"
    return "🩸 en sang"


@dataclass
class TurnChange:
    current: Combatant
    new_round: bool
    expired: list[tuple[Combatant, str]]


@dataclass
class Encounter:
    guild_id: int
    channel_id: int
    round: int = 0
    current_id: str | None = None
    combatants: list[Combatant] = field(default_factory=list)
    tracker_message_id: int | None = None
    next_id: int = 1

    # --- order -----------------------------------------------------------

    def order(self) -> list[Combatant]:
        return sorted(
            self.combatants,
            key=lambda c: (-c.initiative, -c.init_bonus, c.tiebreak),
        )

    def current(self) -> Combatant | None:
        return self.get(self.current_id) if self.current_id else None

    def get(self, combatant_id: str | None) -> Combatant | None:
        return next((c for c in self.combatants if c.id == combatant_id), None)

    def _next_active_after(self, combatant_id: str | None) -> tuple[Combatant, bool]:
        """Next combatant able to act after `combatant_id`, and whether we wrapped."""
        order = self.order()
        active = [c for c in order if not c.is_out]
        if not active:
            raise ValueError(
                "Plus personne ne peut agir : tous les monstres sont hors combat."
            )
        ids = [c.id for c in order]
        start = ids.index(combatant_id) + 1 if combatant_id in ids else 0
        for offset in range(len(order)):
            index = start + offset
            candidate = order[index % len(order)]
            if not candidate.is_out:
                return candidate, index >= len(order)
        return active[0], True

    def advance(self) -> TurnChange:
        if not self.combatants:
            raise ValueError("Personne dans le combat. Ajoute des combattants d’abord.")
        expired: list[tuple[Combatant, str]] = []
        if self.round == 0 or self.current() is None:
            self.round = max(self.round, 1)
            first, _ = self._next_active_after(None)
            self.current_id = first.id
            first.reaction_used = False
            return TurnChange(current=first, new_round=True, expired=expired)

        ending = self.current()
        assert ending is not None
        fresh = set(ending.fresh_conditions)
        ending.fresh_conditions = []
        for key, rounds in list(ending.conditions.items()):
            if rounds is None or key in fresh:
                continue
            if rounds <= 1:
                del ending.conditions[key]
                expired.append((ending, key))
            else:
                ending.conditions[key] = rounds - 1

        following, wrapped = self._next_active_after(ending.id)
        if wrapped:
            self.round += 1
        self.current_id = following.id
        # A creature gets its reaction back at the start of its turn.
        following.reaction_used = False
        return TurnChange(current=following, new_round=wrapped, expired=expired)

    # --- roster ----------------------------------------------------------

    def add(self, combatant: Combatant) -> Combatant:
        combatant.id = f"c{self.next_id}"
        self.next_id += 1
        self.combatants.append(combatant)
        return combatant

    def remove(self, combatant: Combatant) -> None:
        if combatant.id == self.current_id:
            others = [
                c for c in self.combatants if c.id != combatant.id and not c.is_out
            ]
            if others:
                following, wrapped = self._next_active_after(combatant.id)
                if wrapped:
                    self.round += 1
                self.current_id = following.id
            else:
                self.current_id = None
        self.combatants = [c for c in self.combatants if c.id != combatant.id]

    def set_condition(self, combatant: Combatant, key: str, rounds: int | None) -> None:
        combatant.conditions[key] = rounds
        if combatant.id == self.current_id and key not in combatant.fresh_conditions:
            combatant.fresh_conditions.append(key)

    def clear_condition(self, combatant: Combatant, key: str) -> None:
        combatant.conditions.pop(key, None)
        if key in combatant.fresh_conditions:
            combatant.fresh_conditions.remove(key)

    def player(self, user_id: int) -> Combatant | None:
        return next(
            (c for c in self.combatants if c.is_player and c.user_id == user_id), None
        )

    def monster_names(self, base: str, count: int) -> list[str]:
        """Names for `count` new monsters called `base`, numbering when needed."""
        base_key = fold_lookup_key(base)
        taken: list[int] = []
        bare: Combatant | None = None
        for combatant in self.combatants:
            if combatant.is_player:
                continue
            if fold_lookup_key(combatant.name) == base_key:
                bare = combatant
                continue
            match = _NUMBERED_NAME.match(combatant.name)
            if match and fold_lookup_key(match.group(1)) == base_key:
                taken.append(int(match.group(2)))
        if count == 1 and bare is None and not taken:
            return [base]
        if bare is not None:
            bare.name = f"{bare.name} 1"
            taken.append(1)
        start = max(taken, default=0) + 1
        return [f"{base} {start + offset}" for offset in range(count)]

    def find(self, query: str) -> Combatant:
        """Resolve a target typed by a player: exact name, then unique prefix."""
        key = fold_lookup_key(query)
        if not key:
            raise ValueError("Précise une cible.")
        # `gobelin 1`, `gobelin1` and `Gobelin_1` all name `Gobelin 1`.
        compact = key.replace("_", "")
        names = {
            c.id: fold_lookup_key(c.name).replace("_", "") for c in self.combatants
        }
        exact = [c for c in self.combatants if names[c.id] == compact]
        if len(exact) == 1:
            return exact[0]
        prefix = [c for c in self.combatants if names[c.id].startswith(compact)]
        if len(prefix) == 1:
            return prefix[0]
        if prefix:
            listing = ", ".join(c.name for c in self.order() if c in prefix)
            raise ValueError(f"`{query}` peut désigner plusieurs cibles : {listing}.")
        listing = ", ".join(c.name for c in self.order()) or "personne"
        raise ValueError(f"Pas de `{query}` dans le combat. Combattants : {listing}.")

    def find_prefix(self, tokens: list[str]) -> tuple[Combatant, list[str]]:
        """Longest leading run of `tokens` naming a combatant, and the rest."""
        last_error: ValueError | None = None
        for length in range(len(tokens), 0, -1):
            try:
                return self.find(" ".join(tokens[:length])), tokens[length:]
            except ValueError as exc:
                if last_error is None or "plusieurs" in str(exc):
                    last_error = exc
        raise last_error or ValueError("Précise une cible.")

    # --- storage ---------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["combatants"] = [c.to_dict() for c in self.combatants]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Encounter":
        payload = dict(data)
        payload["combatants"] = [
            Combatant.from_dict(item) for item in data.get("combatants", [])
        ]
        return cls(**payload)


def roll_initiative(bonus: int) -> int:
    return random.randint(1, 20) + bonus


def apply_monster_hp(combatant: Combatant, delta: int) -> tuple[int, int]:
    previous = combatant.hp
    combatant.hp = max(0, min(combatant.hp_max, combatant.hp + delta))
    return previous, combatant.hp


def _key(guild_id: int, channel_id: int) -> str:
    return f"encounter:{guild_id}:{channel_id}"


def load_encounter(*, guild_id: int, channel_id: int) -> Encounter | None:
    data = get_json(_key(guild_id, channel_id))
    return Encounter.from_dict(data) if data else None


def save_encounter(encounter: Encounter) -> None:
    set_json(_key(encounter.guild_id, encounter.channel_id), encounter.to_dict())


def delete_encounter(*, guild_id: int, channel_id: int) -> None:
    delete_json(_key(guild_id, channel_id))
