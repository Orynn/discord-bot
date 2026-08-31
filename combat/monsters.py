from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from combat.cards import parse_damage_roll
from srd import fivetools
from srd.fivetools_parser import format_damage_type_label

_DAMAGE_TAG = re.compile(r"\{@damage\s+([^}|]+)", re.IGNORECASE)
_DAMAGE_TYPE = re.compile(
    r"\{@damage\s+[^}|]+\}\s*\)?\s*"
    r"(Acid|Bludgeoning|Cold|Fire|Force|Lightning|Necrotic|Piercing|Poison|Psychic|Radiant|Slashing|Thunder)",
    re.IGNORECASE,
)
_HIT_TAG = re.compile(r"\{@hit\s+([^}|]+)", re.IGNORECASE)
_HP_LEADING = re.compile(r"(\d+)")
_AC_NUMBER = re.compile(r"(\d+)")
_MULTI_COUNT = re.compile(
    r"\b(two|three|four|2|3|4|deux|trois|quatre)\b",
    re.IGNORECASE,
)
_MULTI_WORDS = {
    "two": 2,
    "trois": 3,
    "three": 3,
    "four": 4,
    "deux": 2,
    "quatre": 4,
    "2": 2,
    "3": 3,
    "4": 4,
}

DEFAULT_MONSTER_AC = 10
DEFAULT_MONSTER_ATTACK_BONUS = 4


@dataclass(frozen=True)
class MonsterProfile:
    name: str
    hp: int
    ac: int
    attack_bonus: int
    attack_name: str
    dice_count: int
    dice_sides: int
    flat_modifier: int
    damage_type_label: str | None
    traits: tuple[str, ...]
    attacks: int = 1


def _block_text(block: dict[str, Any]) -> str:
    parts: list[str] = []
    for entry in block.get("entries") or []:
        if isinstance(entry, str):
            parts.append(entry)
    return " ".join(parts)


def _named_blocks(monster: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for key in keys:
        for block in monster.get(key) or []:
            if isinstance(block, dict) and block.get("name"):
                blocks.append(block)
    return blocks


def _trait_names(monster: dict[str, Any], *, limit: int = 2) -> tuple[str, ...]:
    names: list[str] = []
    for block in _named_blocks(monster, "trait", "bonus"):
        name = str(block["name"]).strip()
        if name and name not in names:
            names.append(name)
        if len(names) >= limit:
            break
    return tuple(names)


def _parse_hp(monster: dict[str, Any]) -> int | None:
    raw = monster.get("hp")
    if isinstance(raw, dict) and raw.get("average") is not None:
        try:
            return int(raw["average"])
        except (TypeError, ValueError):
            return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        match = _HP_LEADING.search(raw)
        if match:
            return int(match.group(1))
    return None


def _parse_ac(monster: dict[str, Any]) -> int:
    raw = monster.get("ac")
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict) and first.get("ac") is not None:
            try:
                return int(first["ac"])
            except (TypeError, ValueError):
                pass
        if isinstance(first, (int, float)):
            return int(first)
        if isinstance(first, str):
            match = _AC_NUMBER.search(first)
            if match:
                return int(match.group(1))
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        match = _AC_NUMBER.search(raw)
        if match:
            return int(match.group(1))
    return DEFAULT_MONSTER_AC


def _parse_hit_bonus(text: str) -> int | None:
    match = _HIT_TAG.search(text)
    if match is None:
        return None
    try:
        return int(str(match.group(1)).strip())
    except (TypeError, ValueError):
        return None


def _parse_attack(
    monster: dict[str, Any],
) -> tuple[str, int, int, int, str | None, int]:
    for block in _named_blocks(monster, "action"):
        text = _block_text(block)
        match = _DAMAGE_TAG.search(text)
        if match is None:
            continue
        count, sides, flat = parse_damage_roll(match.group(1))
        if count <= 0 or sides <= 0:
            continue
        type_match = _DAMAGE_TYPE.search(text)
        type_label = (
            format_damage_type_label(type_match.group(1)) if type_match else None
        )
        hit = _parse_hit_bonus(text)
        return (
            str(block["name"]),
            count,
            sides,
            flat,
            type_label,
            hit if hit is not None else DEFAULT_MONSTER_ATTACK_BONUS,
        )
    return "Claw", 1, 6, 0, None, DEFAULT_MONSTER_ATTACK_BONUS


def _parse_attacks(monster: dict[str, Any]) -> int:
    for block in _named_blocks(monster, "action"):
        name = str(block.get("name") or "").lower()
        if "multiattack" not in name and "attaques multiples" not in name:
            continue
        text = f"{name} {_block_text(block)}"
        match = _MULTI_COUNT.search(text)
        if match is None:
            return 2
        return _MULTI_WORDS.get(match.group(1).lower(), 2)
    return 1


def profile_from_monster(monster: dict[str, Any]) -> MonsterProfile:
    attack_name, count, sides, flat, type_label, attack_bonus = _parse_attack(monster)
    hp = _parse_hp(monster) or 20
    return MonsterProfile(
        name=str(monster.get("name") or "Monster"),
        hp=max(1, hp),
        ac=_parse_ac(monster),
        attack_bonus=attack_bonus,
        attack_name=attack_name,
        dice_count=count,
        dice_sides=sides,
        flat_modifier=flat,
        damage_type_label=type_label,
        traits=_trait_names(monster),
        attacks=_parse_attacks(monster),
    )


async def lookup_monster_profile(name: str) -> MonsterProfile | None:
    query = name.strip()
    if not query:
        return None
    try:
        monster = await fivetools.search_monster(query)
    except fivetools.FiveToolsError:
        return None
    return profile_from_monster(monster)
