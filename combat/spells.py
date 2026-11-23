"""Spells and monster save actions (breath weapons) for the combat tracker.

Both become a `SpellInfo`: a saving throw or an attack roll, damage or healing,
conditions on a failed save, concentration and duration.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from combat.attacks import DamagePart, damage_type_key, strip_tags
from sheets.data import CharacterSheet, fold_lookup_key
from sheets.dice import parse_dice
from srd import fivetools

SAVE_ABILITIES: dict[str, str] = {
    "strength": "str",
    "dexterity": "dex",
    "constitution": "con",
    "intelligence": "int",
    "wisdom": "wis",
    "charisma": "cha",
    **{short: short for short in ("str", "dex", "con", "int", "wis", "cha")},
}

# Spells that put one of our tracked effects on their targets.
SPELL_EFFECTS: dict[str, str] = {"bless": "blessed", "bane": "baned"}

SPELLCASTING_BY_CLASS: dict[str, str] = {
    "wizard": "int",
    "magicien": "int",
    "artificer": "int",
    "artificier": "int",
    "cleric": "wis",
    "clerc": "wis",
    "pretre": "wis",
    "druid": "wis",
    "druide": "wis",
    "ranger": "wis",
    "rodeur": "wis",
    "bard": "cha",
    "barde": "cha",
    "sorcerer": "cha",
    "ensorceleur": "cha",
    "warlock": "cha",
    "occultiste": "cha",
    "sorcier": "cha",
    "paladin": "cha",
}

# Spells whose damage only happens later (burning webs…), not when cast.
NO_DAMAGE_ON_CAST = frozenset({"web", "spike growth", "wall of fire", "wall of thorns"})

# Spells that split into several rolls: (base count, extra per slot level above).
PROJECTILES: dict[str, tuple[int, int]] = {
    "magic missile": (3, 1),
    "scorching ray": (3, 1),
}
# Eldritch Blast: beams by character level.
ELDRITCH_BLAST_BEAMS = ((17, 4), (11, 3), (5, 2), (1, 1))

# French names players type → the English 5etools name.
SPELL_ALIASES_FR: dict[str, str] = {
    "boule_de_feu": "fireball",
    "trait_de_feu": "fire bolt",
    "projectile_magique": "magic missile",
    "soins": "cure wounds",
    "soin_des_blessures": "cure wounds",
    "soins_des_blessures": "cure wounds",
    "mot_de_guerison": "healing word",
    "rayon_de_givre": "ray of frost",
    "eclair": "lightning bolt",
    "flamme_sacree": "sacred flame",
    "decharge_occulte": "eldritch blast",
    "immobilisation_de_personne": "hold person",
    "immobiliser_un_humanoide": "hold person",
    "toile_d_araignee": "web",
    "vague_tonnante": "thunderwave",
    "rayon_ardent": "scorching ray",
    "mains_brulantes": "burning hands",
    "poigne_electrique": "shocking grasp",
    "marque_du_chasseur": "hunter's mark",
    "benediction": "bless",
    "fleau": "bane",
    "eclair_tracant": "guiding bolt",
    "trait_guide": "guiding bolt",
    "blessure": "inflict wounds",
    "infliction_de_blessures": "inflict wounds",
    "moquerie_cruelle": "vicious mockery",
    "bouffee_de_poison": "poison spray",
    "contact_glacial": "chill touch",
    "flammes": "produce flame",
    "glas": "toll the dead",
    "tempete_de_grele": "ice storm",
    "cone_de_froid": "cone of cold",
    "colonne_de_flamme": "flame strike",
    "arme_spirituelle": "spiritual weapon",
    "esprits_gardiens": "spirit guardians",
    "nuee_de_meteores": "meteor swarm",
    "sommeil": "sleep",
    "charme_personne": "charm person",
    "peur": "fear",
    "lenteur": "slow",
    "image_miroir": "mirror image",
    "bouclier": "shield",
}

_DICE_TAG = re.compile(r"\{@(?:damage|dice)\s+([^}|]+)", re.IGNORECASE)
_SCALE_TAG = re.compile(
    r"\{@scale(?:damage|dice)\s+[^|}]+\|[^|}]+\|([^}|]+)", re.IGNORECASE
)
_DAMAGE_PART = re.compile(
    r"\{@damage\s+([^}|]+)\}\)?\s*(?P<type>[A-Za-z]+)\s+damage", re.IGNORECASE
)
_HALF = re.compile(r"half\s+(?:as\s+much\s+)?(?:the\s+)?damage", re.IGNORECASE)
_ACT_SAVE = re.compile(r"\{@actSave\s+(\w+)\}", re.IGNORECASE)
_DC = re.compile(r"\{@dc\s+(\d+)", re.IGNORECASE)
_HIT = re.compile(r"\{@hit\s+([+-]?\d+)", re.IGNORECASE)
_CONDITION_TAG = re.compile(r"\{@condition\s+([^}|]+)", re.IGNORECASE)


@dataclass
class SpellInfo:
    name: str
    level: int = 0
    save: str | None = None
    attack: str | None = None  # "R" ranged or "M" melee spell attack
    damage: list[DamagePart] = field(default_factory=list)
    heal_dice: str | None = None
    heal_adds_modifier: bool = False
    half_on_save: bool = False
    conditions: list[str] = field(default_factory=list)
    concentration: bool = False
    duration_rounds: int | None = None
    upcast_step: str | None = None
    cantrip_scaling: dict[str, str] = field(default_factory=dict)
    # Monster save actions carry their own DC.
    dc: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpellInfo":
        payload = {
            key: value for key, value in data.items() if key in cls.__dataclass_fields__
        }
        payload["damage"] = [DamagePart(**part) for part in data.get("damage", [])]
        return cls(**payload)


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [text for item in node for text in _strings(item)]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    return []


def _valid_dice(text: str) -> bool:
    try:
        parse_dice(text)
    except ValueError:
        return False
    return True


def _damage_parts(text: str, fallback_types: list[str]) -> list[DamagePart]:
    parts: list[DamagePart] = []
    for match in _DAMAGE_PART.finditer(text):
        dice = "".join(match.group(1).split())
        if _valid_dice(dice):
            parts.append(
                DamagePart(dice=dice, type=damage_type_key(match.group("type")) or "")
            )
    if parts or not fallback_types:
        return parts[:1] if parts and _is_choice(text) else parts
    first = _DICE_TAG.search(text)
    if first:
        dice = "".join(first.group(1).split())
        if _valid_dice(dice):
            return [DamagePart(dice=dice, type=fallback_types[0])]
    return []


def _is_choice(text: str) -> bool:
    # `… Fire damage or Cold damage (your choice)`: keep the first one only.
    return "your choice" in text.lower() or "of your choice" in text.lower()


def _duration(raw: dict[str, Any] | None) -> tuple[bool, int | None]:
    durations = (raw or {}).get("duration") or []
    if not durations or not isinstance(durations[0], dict):
        return False, None
    first = durations[0]
    concentration = bool(first.get("concentration"))
    timed = first.get("duration") or {}
    amount = int(timed.get("amount") or 0)
    unit = str(timed.get("type") or "")
    rounds = {"round": amount, "minute": amount * 10}.get(unit)
    return concentration, rounds


def spell_from_5etools(spell: dict[str, Any], raw: dict[str, Any] | None) -> SpellInfo:
    source = raw or spell
    text = " ".join(_strings(source.get("entries")))
    higher = " ".join(_strings(source.get("entriesHigherLevel")))
    saves = [
        SAVE_ABILITIES.get(str(s).lower(), "") for s in source.get("savingThrow") or []
    ]
    attacks = [str(a).upper() for a in source.get("spellAttack") or []]
    types = [damage_type_key(str(t)) or "" for t in source.get("damageInflict") or []]
    concentration, rounds = _duration(raw)
    level = source.get("level")
    level = int(level) if isinstance(level, int) or str(level).isdigit() else 0
    name = str(spell.get("name") or source.get("name") or "Sort")

    heal_dice = None
    heal_adds = False
    misc = {str(tag).upper() for tag in source.get("miscTags") or []}
    if "HL" in misc and not types:
        match = _DICE_TAG.search(text)
        if match and _valid_dice("".join(match.group(1).split())):
            heal_dice = "".join(match.group(1).split())
            heal_adds = "spellcasting ability modifier" in text.lower()

    scaling = source.get("scalingLevelDice")
    if isinstance(scaling, list):
        scaling = scaling[0] if scaling else None
    step = _SCALE_TAG.search(higher)
    conditions = [str(c).lower() for c in source.get("conditionInflict") or []]
    plain_name = fold_lookup_key(name).replace("_", " ")
    effect = SPELL_EFFECTS.get(plain_name)
    if effect:
        conditions.append(effect)
    return SpellInfo(
        name=name,
        level=level,
        save=saves[0] if saves and saves[0] else None,
        attack=attacks[0] if attacks else None,
        damage=(
            _damage_parts(text, types)
            if types and plain_name not in NO_DAMAGE_ON_CAST
            else []
        ),
        heal_dice=heal_dice,
        heal_adds_modifier=heal_adds,
        half_on_save=bool(_HALF.search(text)),
        conditions=conditions,
        concentration=concentration,
        duration_rounds=rounds,
        upcast_step="".join(step.group(1).split()) if step else None,
        cantrip_scaling=dict((scaling or {}).get("scaling") or {})
        if isinstance(scaling, dict)
        else {},
    )


async def lookup_spell(query: str) -> SpellInfo:
    key = fold_lookup_key(query)
    english = SPELL_ALIASES_FR.get(key, query)
    try:
        spell = await fivetools.search_spell(english)
    except fivetools.FiveToolsError as exc:
        raise ValueError(
            f"Sort introuvable dans 5etools : `{query}`. Donne son nom anglais "
            "(ex. `fireball`)."
        ) from exc
    raw = fivetools.get_index().spells_by_slug.get(str(spell.get("slug") or ""))
    return spell_from_5etools(spell, raw)


def monster_save_actions(monster: dict[str, Any]) -> list[SpellInfo]:
    """Actions such as `Fire Breath`: `{@actSave dex} {@dc 21} … damage`."""
    actions: list[SpellInfo] = []
    for key in ("action", "bonus", "legendary", "reaction"):
        for block in monster.get(key) or []:
            if not isinstance(block, dict) or not block.get("name"):
                continue
            text = " ".join(_strings(block.get("entries")))
            save = _ACT_SAVE.search(text)
            dc = _DC.search(text)
            if save is None or dc is None:
                continue
            fail_text = text.split("{@actSaveSuccess}")[0]
            actions.append(
                SpellInfo(
                    name=strip_tags(str(block["name"])),
                    save=SAVE_ABILITIES.get(save.group(1).lower()),
                    damage=_damage_parts(text, []),
                    half_on_save=bool(_HALF.search(text)),
                    conditions=[
                        match.group(1).strip().lower()
                        for match in _CONDITION_TAG.finditer(fail_text)
                    ],
                    dc=int(dc.group(1)),
                )
            )
    return actions


_PLAIN_DC = re.compile(r"\bDC\s*(\d+)", re.IGNORECASE)
_PLAIN_HIT = re.compile(r"([+-]\d+)\s+to\s+hit", re.IGNORECASE)


def monster_spellcasting(monster: dict[str, Any]) -> tuple[int | None, int | None]:
    """(spell save DC, spell attack bonus) from a statblock's Spellcasting."""
    text = " ".join(_strings(monster.get("spellcasting")))
    dc = _DC.search(text) or _PLAIN_DC.search(text)
    hit = _HIT.search(text) or _PLAIN_HIT.search(text)
    return (int(dc.group(1)) if dc else None, int(hit.group(1)) if hit else None)


def spellcasting_ability(sheet: CharacterSheet) -> str:
    for word in fold_lookup_key(sheet.char_class).split("_"):
        if word in SPELLCASTING_BY_CLASS:
            return SPELLCASTING_BY_CLASS[word]
    return max(("int", "wis", "cha"), key=lambda key: sheet.abilities.get(key, 10))


def caster_numbers(sheet: CharacterSheet) -> tuple[int, int, int]:
    """(save DC, spell attack bonus, ability modifier) of a player caster."""
    ability = spellcasting_ability(sheet)
    modifier = (sheet.abilities.get(ability, 10) - 10) // 2
    bonus = sheet.get_prof_bonus() + modifier
    return 8 + bonus, bonus, modifier


def _add_dice(base: str, step: str, times: int) -> str:
    """`8d6` + 2 × `1d6` → `10d6`; different dice are appended."""
    if times <= 0:
        return base
    main = parse_dice(base)
    extra = parse_dice(step)
    if extra.sides == main.sides and not main.extra_dice:
        count = main.count + extra.count * times
        flat = main.flat_modifier + extra.flat_modifier * times
        return f"{count}d{main.sides}" + (
            f"+{flat}" if flat > 0 else str(flat) if flat else ""
        )
    return f"{base}+{extra.count * times}d{extra.sides}"


def _cantrip_dice(info: SpellInfo, character_level: int) -> str | None:
    if not info.cantrip_scaling:
        return None
    best = max(
        (
            int(level)
            for level in info.cantrip_scaling
            if int(level) <= max(character_level, 1)
        ),
        default=None,
    )
    return info.cantrip_scaling.get(str(best)) if best is not None else None


def damage_for_cast(
    info: SpellInfo, *, cast_level: int, character_level: int
) -> list[DamagePart]:
    parts = [DamagePart(dice=p.dice, type=p.type) for p in info.damage]
    if not parts:
        return parts
    cantrip = _cantrip_dice(info, character_level)
    if info.level == 0 and cantrip and _valid_dice(cantrip):
        parts[0].dice = cantrip
    elif info.upcast_step and cast_level > info.level:
        parts[0].dice = _add_dice(
            parts[0].dice, info.upcast_step, cast_level - info.level
        )
    return parts


def projectile_count(info: SpellInfo, *, cast_level: int, character_level: int) -> int:
    """How many separate rolls the spell makes (darts, rays, beams)."""
    plain = fold_lookup_key(info.name).replace("_", " ")
    if plain == "eldritch blast":
        return next(
            beams for level, beams in ELDRITCH_BLAST_BEAMS if character_level >= level
        )
    base, per_level = PROJECTILES.get(plain, (1, 0))
    return base + per_level * max(0, cast_level - max(info.level, 1))


def heal_for_cast(info: SpellInfo, *, cast_level: int) -> str | None:
    if not info.heal_dice:
        return None
    if info.upcast_step and cast_level > info.level:
        return _add_dice(info.heal_dice, info.upcast_step, cast_level - info.level)
    return info.heal_dice
