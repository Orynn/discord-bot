from __future__ import annotations

from typing import Any

from sheets.containers import type_code
from sheets.data import CharacterSheet, ability_modifier
from sheets.equipment import ITEM_KIND_ARMOR, InventoryItem

LIGHT = "LA"
MEDIUM = "MA"
HEAVY = "HA"
SHIELD = "S"
MEDIUM_DEX_CAP = 2


def _parse_ac_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace("+", "")
    try:
        return int(float(text))
    except ValueError:
        return None


def armor_type_code(raw: dict[str, Any] | None) -> str:
    code = type_code(raw).upper()
    if code in {LIGHT, MEDIUM, HEAVY, SHIELD}:
        return code
    if not raw:
        return ""
    if raw.get("heavy"):
        return HEAVY
    if raw.get("medium"):
        return MEDIUM
    if raw.get("shield") or code == SHIELD:
        return SHIELD
    if raw.get("armor") or raw.get("light"):
        return LIGHT
    return ""


def dex_bonus_for_armor(type_code_value: str, dex_mod: int) -> int:
    if type_code_value == HEAVY:
        return 0
    if type_code_value == MEDIUM:
        return min(dex_mod, MEDIUM_DEX_CAP)
    if type_code_value == LIGHT:
        return dex_mod
    return 0


def _bonus_ac(raw: dict[str, Any] | None) -> int:
    if not raw:
        return 0
    return _parse_ac_number(raw.get("bonusAc")) or 0


def unarmored_ac(
    sheet: CharacterSheet,
    *,
    has_shield: bool,
) -> int:
    dex = ability_modifier(sheet.abilities.get("dex", 10))
    parts = (sheet.char_class or "").lower().strip().replace("-", " ").split()
    class_key = parts[0] if parts else ""
    if class_key == "barbarian":
        return 10 + dex + ability_modifier(sheet.abilities.get("con", 10))
    if class_key == "monk" and not has_shield:
        return 10 + dex + ability_modifier(sheet.abilities.get("wis", 10))
    return 10 + dex


def equipped_body_armor(sheet: CharacterSheet) -> InventoryItem | None:
    for item in sheet.equipment.equipped_items():
        if sheet.equipment.is_shield(item):
            continue
        if item.kind == ITEM_KIND_ARMOR or sheet.equipment.is_worn_when_equipped(item):
            return item
    return None


def equipped_shield(sheet: CharacterSheet) -> InventoryItem | None:
    for item in sheet.equipment.equipped_items():
        if sheet.equipment.is_shield(item):
            return item
    return None


def has_ac_gear(sheet: CharacterSheet) -> bool:
    return equipped_body_armor(sheet) is not None or equipped_shield(sheet) is not None


def computed_ac(sheet: CharacterSheet) -> int | None:
    dex = ability_modifier(sheet.abilities.get("dex", 10))
    body = equipped_body_armor(sheet)
    shield = equipped_shield(sheet)
    total = 0

    if body is not None:
        raw = sheet.equipment._raw_for(body)
        base = _parse_ac_number((raw or {}).get("ac"))
        if base is None:
            return None
        category = armor_type_code(raw)
        if category == SHIELD:
            return None
        total = base + dex_bonus_for_armor(category, dex) + _bonus_ac(raw)
    else:
        total = unarmored_ac(sheet, has_shield=shield is not None)

    if shield is not None:
        raw = sheet.equipment._raw_for(shield)
        bonus = _parse_ac_number((raw or {}).get("ac"))
        if bonus is None:
            bonus = 2
        total += bonus + _bonus_ac(raw)

    return total


def apply_armor_ac(sheet: CharacterSheet, *, force: bool = False) -> int:
    value = computed_ac(sheet)
    if value is None:
        return sheet.ac
    if force or has_ac_gear(sheet):
        sheet.ac = value
    return sheet.ac


def format_ac_field(sheet: CharacterSheet) -> str:
    names: list[str] = []
    body = equipped_body_armor(sheet)
    shield = equipped_shield(sheet)
    if body is not None:
        names.append(body.name)
    if shield is not None:
        names.append(shield.name)
    if names:
        return f"{sheet.ac}\n{', '.join(names)}"
    return str(sheet.ac)
