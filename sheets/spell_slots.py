from __future__ import annotations

from dataclasses import dataclass, field

SPELL_LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# Full casters (bard, cleric, druid, sorcerer, wizard) — by class level.
FULL_CASTER_SLOTS: dict[int, tuple[int, ...]] = {
    1: (2, 0, 0, 0, 0, 0, 0, 0, 0),
    2: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    3: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    4: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    5: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    6: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    7: (4, 3, 3, 1, 0, 0, 0, 0, 0),
    8: (4, 3, 3, 2, 0, 0, 0, 0, 0),
    9: (4, 3, 3, 3, 1, 0, 0, 0, 0),
    10: (4, 3, 3, 3, 2, 0, 0, 0, 0),
    11: (4, 3, 3, 3, 2, 1, 0, 0, 0),
    12: (4, 3, 3, 3, 2, 1, 0, 0, 0),
    13: (4, 3, 3, 3, 2, 1, 1, 0, 0),
    14: (4, 3, 3, 3, 2, 1, 1, 0, 0),
    15: (4, 3, 3, 3, 2, 1, 1, 1, 0),
    16: (4, 3, 3, 3, 2, 1, 1, 1, 0),
    17: (4, 3, 3, 3, 2, 1, 1, 1, 1),
    18: (4, 3, 3, 3, 3, 1, 1, 1, 1),
    19: (4, 3, 3, 3, 3, 2, 1, 1, 1),
    20: (4, 3, 3, 3, 3, 2, 2, 1, 1),
}

# Half casters (paladin, ranger, artificer) — by class level.
HALF_CASTER_SLOTS: dict[int, tuple[int, ...]] = {
    1: (0, 0, 0, 0, 0, 0, 0, 0, 0),
    2: (2, 0, 0, 0, 0, 0, 0, 0, 0),
    3: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    4: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    5: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    6: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    7: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    8: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    9: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    10: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    11: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    12: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    13: (4, 3, 3, 1, 0, 0, 0, 0, 0),
    14: (4, 3, 3, 1, 0, 0, 0, 0, 0),
    15: (4, 3, 3, 2, 0, 0, 0, 0, 0),
    16: (4, 3, 3, 2, 0, 0, 0, 0, 0),
    17: (4, 3, 3, 3, 1, 0, 0, 0, 0),
    18: (4, 3, 3, 3, 1, 0, 0, 0, 0),
    19: (4, 3, 3, 3, 2, 0, 0, 0, 0),
    20: (4, 3, 3, 3, 2, 0, 0, 0, 0),
}

# Third casters (eldritch knight, arcane trickster) — by class level.
THIRD_CASTER_SLOTS: dict[int, tuple[int, ...]] = {
    1: (0, 0, 0, 0, 0, 0, 0, 0, 0),
    2: (0, 0, 0, 0, 0, 0, 0, 0, 0),
    3: (2, 0, 0, 0, 0, 0, 0, 0, 0),
    4: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    5: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    6: (3, 0, 0, 0, 0, 0, 0, 0, 0),
    7: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    8: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    9: (4, 2, 0, 0, 0, 0, 0, 0, 0),
    10: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    11: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    12: (4, 3, 0, 0, 0, 0, 0, 0, 0),
    13: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    14: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    15: (4, 3, 2, 0, 0, 0, 0, 0, 0),
    16: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    17: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    18: (4, 3, 3, 0, 0, 0, 0, 0, 0),
    19: (4, 3, 3, 1, 0, 0, 0, 0, 0),
    20: (4, 3, 3, 1, 0, 0, 0, 0, 0),
}

# Warlock pact magic: (slot_count, slot_level) by class level.
WARLOCK_PACT: dict[int, tuple[int, int]] = {
    1: (1, 1),
    2: (2, 1),
    3: (2, 2),
    4: (2, 2),
    5: (2, 3),
    6: (2, 3),
    7: (2, 4),
    8: (2, 4),
    9: (2, 5),
    10: (2, 5),
    11: (3, 5),
    12: (3, 5),
    13: (3, 5),
    14: (3, 5),
    15: (3, 5),
    16: (3, 5),
    17: (4, 5),
    18: (4, 5),
    19: (4, 5),
    20: (4, 5),
}

FULL_CASTERS = frozenset({"bard", "cleric", "druid", "sorcerer", "wizard"})
HALF_CASTERS = frozenset({"paladin", "ranger", "artificer"})
THIRD_CASTERS = frozenset({"fighter", "rogue"})  # only with EK / AT subclasses
WARLOCK = "warlock"

_ORDINAL = {
    1: "1st",
    2: "2nd",
    3: "3rd",
    4: "4th",
    5: "5th",
    6: "6th",
    7: "7th",
    8: "8th",
    9: "9th",
}


def level_label(level: int) -> str:
    return _ORDINAL.get(level, f"{level}th")


def _class_key(char_class: str) -> str:
    if not char_class:
        return ""
    return char_class.lower().strip().split()[0]


def _subclass_key(subclass: str) -> str:
    return subclass.lower().strip()


@dataclass
class SpellSlots:
    """Track spell slots by level (1–9). Values are current remaining slots."""

    current: dict[int, int] = field(default_factory=dict)
    maximum: dict[int, int] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> "SpellSlots":
        if not data:
            return cls()
        current_raw = data.get("current", {})
        maximum_raw = data.get("maximum", data.get("max", {}))
        current: dict[int, int] = {}
        maximum: dict[int, int] = {}
        for key, value in maximum_raw.items():
            level = int(key)
            if level not in SPELL_LEVELS:
                continue
            maximum[level] = max(0, int(value))
        for key, value in current_raw.items():
            level = int(key)
            if level not in SPELL_LEVELS:
                continue
            maximum.setdefault(level, max(0, int(value)))
            current[level] = max(0, int(value))
        for level, max_slots in maximum.items():
            current[level] = min(current.get(level, max_slots), max_slots)
        return cls(current=current, maximum=maximum)

    def to_dict(self) -> dict[str, dict[str, int]]:
        levels = sorted(set(self.current) | set(self.maximum))
        return {
            "current": {str(level): int(self.current.get(level, 0)) for level in levels},
            "maximum": {str(level): int(self.maximum.get(level, 0)) for level in levels},
        }

    def has_slots(self) -> bool:
        return any(max_slots > 0 for max_slots in self.maximum.values())

    def get_current(self, level: int) -> int:
        return int(self.current.get(level, 0))

    def get_maximum(self, level: int) -> int:
        return int(self.maximum.get(level, 0))

    def set_level(self, level: int, maximum: int, current: int | None = None) -> None:
        if level not in SPELL_LEVELS:
            raise ValueError("Spell slot level must be between 1 and 9.")
        if maximum < 0:
            raise ValueError("Maximum slots cannot be negative.")
        if maximum == 0:
            self.current.pop(level, None)
            self.maximum.pop(level, None)
            return
        self.maximum[level] = maximum
        if current is None:
            self.current[level] = maximum
        else:
            if current < 0:
                raise ValueError("Current slots cannot be negative.")
            self.current[level] = min(current, maximum)

    def use(self, level: int, count: int = 1) -> None:
        if level not in SPELL_LEVELS:
            raise ValueError("Spell slot level must be between 1 and 9.")
        if count < 1:
            raise ValueError("Must use at least 1 slot.")
        available = self.get_current(level)
        if available < count:
            raise ValueError(
                f"Not enough {level_label(level)}-level slots "
                f"({available}/{self.get_maximum(level)} remaining)."
            )
        self.current[level] = available - count

    def recover(self, level: int | None = None, count: int | None = None) -> None:
        if level is None:
            self.restore_all()
            return
        if level not in SPELL_LEVELS:
            raise ValueError("Spell slot level must be between 1 and 9.")
        maximum = self.get_maximum(level)
        if maximum <= 0:
            raise ValueError(f"No {level_label(level)}-level slots configured.")
        if count is None:
            self.current[level] = maximum
            return
        if count < 1:
            raise ValueError("Must recover at least 1 slot.")
        self.current[level] = min(maximum, self.get_current(level) + count)

    def restore_all(self) -> None:
        for level, maximum in self.maximum.items():
            self.current[level] = maximum

    def clear(self) -> None:
        self.current.clear()
        self.maximum.clear()

    def apply_table(self, table: tuple[int, ...], *, fill: bool = True) -> None:
        self.clear()
        for index, maximum in enumerate(table, start=1):
            if maximum > 0:
                self.maximum[index] = maximum
                self.current[index] = maximum if fill else 0

    def format(self) -> str:
        if not self.has_slots():
            return "—"
        parts: list[str] = []
        for level in SPELL_LEVELS:
            maximum = self.get_maximum(level)
            if maximum <= 0:
                continue
            current = self.get_current(level)
            parts.append(f"{level_label(level)} **{current}/{maximum}**")
        return " · ".join(parts)


def slots_table_for_class(
    char_class: str,
    level: int,
    *,
    subclass: str = "",
) -> tuple[int, ...] | None:
    """Return max slots (levels 1–9) for a single class, or None if unknown/non-caster."""
    if not 1 <= level <= 20:
        raise ValueError("Level must be between 1 and 20.")

    key = _class_key(char_class)
    if not key:
        return None

    if key == WARLOCK:
        count, pact_level = WARLOCK_PACT[level]
        table = [0] * 9
        table[pact_level - 1] = count
        return tuple(table)

    if key in FULL_CASTERS:
        return FULL_CASTER_SLOTS[level]

    if key in HALF_CASTERS:
        return HALF_CASTER_SLOTS[level]

    if key in THIRD_CASTERS:
        sub = _subclass_key(subclass)
        if "eldritch" in sub or "arcane trickster" in sub or "trickster" in sub:
            return THIRD_CASTER_SLOTS[level]
        return None

    return None


def parse_slot_level(value: str) -> int:
    cleaned = value.strip().lower().rstrip("stndrh")
    level = int(cleaned)
    if level not in SPELL_LEVELS:
        raise ValueError("Spell slot level must be between 1 and 9.")
    return level
