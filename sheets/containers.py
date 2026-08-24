import re
from typing import Any

STORED_HANDS = "hands"
STORED_BELT = "belt"
STORED_WORN = "worn"
STORED_LOOSE = "loose"
SPECIAL_LOCATIONS = frozenset({STORED_HANDS, STORED_BELT, STORED_WORN, STORED_LOOSE})
HAND_SLOTS = 2
BELT_SLOTS = 4
DEFAULT_BAG_CAPACITY_LB = 30.0
MAX_BELT_CONTAINER_LB = 6.0
HAND_ALIASES = frozenset({STORED_HANDS, "hand", "mains", "main"})
BELT_ALIASES = frozenset({STORED_BELT, "ceinture", "ceintures"})

_POUCH_NAME = re.compile(r"\b(pouch|bourse|purse)\b", re.IGNORECASE)
_PACK_NAME = re.compile(
    r"\b(backpack|haversack|rucksack|sac à dos|sac-a-dos)\b",
    re.IGNORECASE,
)
_SACK_NAME = re.compile(r"\b(sack|sac|bag|pack)\b", re.IGNORECASE)


def type_code(raw: dict[str, Any] | None) -> str:
    if not raw:
        return ""
    return str(raw.get("type") or "").split("|", 1)[0]


def property_codes(raw: dict[str, Any] | None) -> set[str]:
    if not raw:
        return set()
    codes: set[str] = set()
    for prop in raw.get("property") or []:
        codes.add(str(prop).split("|", 1)[0].upper())
    return codes


def container_capacity_from_raw(
    raw: dict[str, Any] | None,
) -> tuple[float, bool] | None:
    if not raw:
        return None
    capacity = raw.get("containerCapacity")
    if not isinstance(capacity, dict):
        return None
    weights = capacity.get("weight") or []
    if not weights:
        return None
    try:
        pounds = float(weights[0])
    except (TypeError, ValueError):
        return None
    return pounds, bool(capacity.get("weightless"))


def custom_container_capacity(name: str) -> tuple[float, bool] | None:
    if _POUCH_NAME.search(name):
        return 6.0, False
    if _PACK_NAME.search(name):
        return 30.0, False
    if _SACK_NAME.search(name):
        return 30.0, False
    return None


def is_shield_raw(raw: dict[str, Any] | None, *, name: str = "") -> bool:
    if type_code(raw) == "S" or bool(raw and raw.get("shield")):
        return True
    return "shield" in name.lower() or "bouclier" in name.lower()


def is_two_handed_raw(raw: dict[str, Any] | None) -> bool:
    return "2H" in property_codes(raw)


def parse_put_args(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    if not cleaned:
        return "", ""
    parts = re.split(r"\s+in\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    tokens = cleaned.split()
    if len(tokens) >= 2 and tokens[0].casefold() in {"all", "tout", "*"}:
        return tokens[0], " ".join(tokens[1:]).strip()
    split = cleaned.rsplit(maxsplit=1)
    if len(split) == 2:
        return split[0].strip(), split[1].strip()
    return cleaned, ""
