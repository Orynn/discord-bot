"""Monster stats for the tracker, read from the 5etools index or typed by the MJ."""

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from combat.attacks import Attack, damage_types_in, monster_attacks, strip_tags
from combat.spells import SpellInfo, monster_save_actions, monster_spellcasting
from sheets.dice import execute_roll, parse_dice
from srd import fivetools

_LEADING_INT = re.compile(r"-?\d+")
_HP_FORMULA = re.compile(r"\(([^)]*\d+d\d+[^)]*)\)", re.IGNORECASE)
_CR = re.compile(r"^\s*(\d+(?:/\d+)?)")


@dataclass(frozen=True)
class MonsterStats:
    name: str
    hp_average: int
    hp_formula: str | None
    ac: int | None
    init_bonus: int
    source: str = ""
    attacks: tuple[Attack, ...] = ()
    resist: tuple[str, ...] = ()
    immune: tuple[str, ...] = ()
    vulnerable: tuple[str, ...] = ()
    multiattack: str = ""
    saves: tuple[tuple[str, int], ...] = ()
    save_actions: tuple[SpellInfo, ...] = ()
    spell_dc: int | None = None
    spell_attack: int | None = None


def _leading_int(value: Any) -> int | None:
    match = _LEADING_INT.search(str(value or ""))
    return int(match.group(0)) if match else None


def _ability_modifier(score: Any) -> int:
    try:
        return (int(score) - 10) // 2
    except (TypeError, ValueError):
        return 0


def _proficiency_bonus(cr_text: Any) -> int:
    match = _CR.match(str(cr_text or ""))
    if match is None:
        return 2
    cr = math.ceil(Fraction(match.group(1)))
    return 2 + max(0, cr - 1) // 4


def _init_bonus(monster: dict[str, Any]) -> int:
    dex = _ability_modifier(monster.get("dex"))
    raw = monster.get("initiative")
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, dict):
        if isinstance(raw.get("initiative"), (int, float)):
            return int(raw["initiative"])
        proficiency = raw.get("proficiency")
        if isinstance(proficiency, (int, float)):
            return dex + int(proficiency) * _proficiency_bonus(monster.get("cr"))
    return dex


def stats_from_monster(monster: dict[str, Any]) -> MonsterStats:
    """`monster` is a normalized 5etools entry (`hp` like `45 (10d6 + 10)`)."""
    hp_text = str(monster.get("hp") or "")
    formula_match = _HP_FORMULA.search(hp_text)
    formula = "".join(formula_match.group(1).split()) if formula_match else None
    spell_dc, spell_attack = monster_spellcasting(monster)
    return MonsterStats(
        name=str(monster.get("name") or "Monstre"),
        hp_average=max(1, _leading_int(hp_text) or 1),
        hp_formula=formula,
        ac=_leading_int(monster.get("ac")),
        init_bonus=_init_bonus(monster),
        source=str(monster.get("source") or ""),
        attacks=tuple(monster_attacks(monster)),
        resist=tuple(damage_types_in(monster.get("resist"))),
        immune=tuple(damage_types_in(monster.get("immune"))),
        vulnerable=tuple(damage_types_in(monster.get("vulnerable"))),
        multiattack=_multiattack(monster),
        saves=tuple(_saves(monster).items()),
        save_actions=tuple(monster_save_actions(monster)),
        spell_dc=spell_dc,
        spell_attack=spell_attack,
    )


def _saves(monster: dict[str, Any]) -> dict[str, int]:
    """Every saving throw bonus: proficient ones from `save`, else the modifier."""
    listed = monster.get("save") if isinstance(monster.get("save"), dict) else {}
    saves: dict[str, int] = {}
    for ability in ("str", "dex", "con", "int", "wis", "cha"):
        bonus = _leading_int(listed.get(ability)) if listed.get(ability) else None
        saves[ability] = (
            bonus if bonus is not None else _ability_modifier(monster.get(ability))
        )
    return saves


def _multiattack(monster: dict[str, Any]) -> str:
    for block in monster.get("action") or []:
        if (
            isinstance(block, dict)
            and "multiattack" in str(block.get("name", "")).lower()
        ):
            return strip_tags(
                " ".join(
                    str(entry)
                    for entry in block.get("entries") or []
                    if isinstance(entry, str)
                )
            )
    return ""


async def lookup_monster(query: str) -> MonsterStats:
    try:
        monster = await fivetools.search_monster(query)
    except fivetools.FiveToolsError as exc:
        raise ValueError(
            f"Monstre introuvable dans 5etools : `{query}` ({exc}).\n"
            "Donne son nom anglais, ou crée-le à la main : "
            "`bandit pv 11 ca 12 init 1`."
        ) from exc
    return stats_from_monster(monster)


def roll_hp(stats: MonsterStats, *, average: bool = False) -> int:
    if average or not stats.hp_formula:
        return stats.hp_average
    try:
        dice = parse_dice(stats.hp_formula)
    except ValueError:
        return stats.hp_average
    result = execute_roll(dice=dice, sheet=None, modifier_tokens=[], advantage=None)
    return max(1, result.total)
