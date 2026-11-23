"""Attack rolls and damage: monster actions from 5etools, player weapons from the sheet.

Pure rules, no Discord and no storage.
"""

import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from sheets.data import CharacterSheet, fold_lookup_key, proficiency_bonus
from sheets.dice import ParsedDice, RollResult, execute_roll, parse_dice

DAMAGE_TYPES_FR: dict[str, str] = {
    "acid": "acide",
    "bludgeoning": "contondant",
    "cold": "froid",
    "fire": "feu",
    "force": "force",
    "lightning": "foudre",
    "necrotic": "nécrotique",
    "piercing": "perforant",
    "poison": "poison",
    "psychic": "psychique",
    "radiant": "radiant",
    "slashing": "tranchant",
    "thunder": "tonnerre",
}
_DAMAGE_TYPE_ALIASES: dict[str, str] = {
    **{english: english for english in DAMAGE_TYPES_FR},
    **{fold_lookup_key(french): english for english, french in DAMAGE_TYPES_FR.items()},
    "contondants": "bludgeoning",
    "perforants": "piercing",
    "tranchants": "slashing",
}
_WEAPON_DAMAGE_CODES: dict[str, str] = {
    "A": "acid",
    "B": "bludgeoning",
    "C": "cold",
    "F": "fire",
    "O": "force",
    "L": "lightning",
    "N": "necrotic",
    "P": "piercing",
    "I": "poison",
    "Y": "psychic",
    "R": "radiant",
    "S": "slashing",
    "T": "thunder",
}

# French names players type for the weapons stored under their 5etools name.
WEAPON_ALIASES_FR: dict[str, str] = {
    "epee_longue": "longsword",
    "epee_courte": "shortsword",
    "epee_a_deux_mains": "greatsword",
    "dague": "dagger",
    "arc_long": "longbow",
    "arc_court": "shortbow",
    "hache_d_armes": "battleaxe",
    "grande_hache": "greataxe",
    "hachette": "handaxe",
    "rapiere": "rapier",
    "baton": "quarterstaff",
    "masse_d_armes": "mace",
    "arbalete_legere": "light crossbow",
    "arbalete_lourde": "heavy crossbow",
    "arbalete_de_poing": "hand crossbow",
    "cimeterre": "scimitar",
    "marteau_de_guerre": "warhammer",
    "marteau_leger": "light hammer",
    "lance": "spear",
    "javeline": "javelin",
    "fronde": "sling",
    "gourdin": "club",
    "massue": "greatclub",
    "morgenstern": "morningstar",
    "fleau_d_armes": "flail",
    "hallebarde": "halberd",
    "coutille": "glaive",
    "pique": "pike",
    "maillet": "maul",
    "fouet": "whip",
    "serpe": "sickle",
    "trident": "trident",
    "pic_de_guerre": "war pick",
}

UNARMED_NAMES = frozenset(
    {"mains_nues", "poing", "poings", "unarmed", "unarmed_strike"}
)

_TAG = re.compile(r"\{@(\w+)\s*([^}|]*)[^}]*\}")
_HIT = re.compile(r"\{@hit\s+([+-]?\d+)", re.IGNORECASE)
_ATTACK_KIND = re.compile(r"\{@atk[a-z]*\s+([mr,\s]+)\}", re.IGNORECASE)
_DAMAGE_PART = re.compile(
    r"\{@damage\s+([^}|]+)\}\)?\s*(?P<type>[A-Za-z]+)\s+damage",
    re.IGNORECASE,
)
_ADVANTAGE_CONDITION = re.compile(r"^[^.,]*\bif\b[^.]*advantage", re.IGNORECASE)


@dataclass
class DamagePart:
    dice: str
    type: str = ""
    # Only added when the attack roll had advantage (goblins, rogues…).
    needs_advantage: bool = False


@dataclass
class Attack:
    name: str
    hit: int
    damage: list[DamagePart] = field(default_factory=list)
    ranged: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Attack":
        payload = dict(data)
        payload["damage"] = [DamagePart(**part) for part in data.get("damage", [])]
        return cls(**payload)


def damage_type_key(text: str) -> str | None:
    return _DAMAGE_TYPE_ALIASES.get(fold_lookup_key(text))


def damage_type_label(key: str) -> str:
    return DAMAGE_TYPES_FR.get(key, key)


def damage_types_in(text: Any) -> list[str]:
    """Damage types named in a formatted 5etools list (`🔥 Fire, ☠️ Poison`)."""
    words = re.findall(r"[A-Za-z]+", str(text or ""))
    found: list[str] = []
    for word in words:
        key = word.lower()
        if key in DAMAGE_TYPES_FR and key not in found:
            found.append(key)
    return found


def strip_tags(text: str) -> str:
    text = re.sub(
        r"\{@recharge\s*(\d*)\}", lambda m: f"(recharge {m.group(1) or 6})", text
    )
    return " ".join(_TAG.sub(lambda m: m.group(2).strip(), text).split())


def _block_text(block: dict[str, Any]) -> str:
    return " ".join(
        entry for entry in block.get("entries") or [] if isinstance(entry, str)
    )


def monster_attacks(monster: dict[str, Any]) -> list[Attack]:
    """Attack actions (`{@hit N}`) of a 5etools monster, bonus actions included."""
    attacks: list[Attack] = []
    for key in ("action", "bonus"):
        for block in monster.get(key) or []:
            if not isinstance(block, dict) or not block.get("name"):
                continue
            text = _block_text(block)
            hit = _HIT.search(text)
            if hit is None:
                continue
            kind = _ATTACK_KIND.search(text)
            parts: list[DamagePart] = []
            matches = list(_DAMAGE_PART.finditer(text))
            for index, match in enumerate(matches):
                dice = "".join(match.group(1).split())
                if not _valid_dice(dice):
                    continue
                # Text up to the next damage roll: `… if the attack roll had Advantage`.
                stop = (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else len(text)
                )
                after = strip_tags(text[match.end() : stop])
                parts.append(
                    DamagePart(
                        dice=dice,
                        type=damage_type_key(match.group("type")) or "",
                        needs_advantage=bool(_ADVANTAGE_CONDITION.search(after)),
                    )
                )
            attacks.append(
                Attack(
                    name=strip_tags(str(block["name"])),
                    hit=int(hit.group(1)),
                    damage=parts,
                    ranged=bool(
                        kind
                        and "r" in kind.group(1).lower()
                        and "m" not in kind.group(1).lower()
                    ),
                )
            )
    return attacks


def _valid_dice(text: str) -> bool:
    try:
        parse_dice(text)
    except ValueError:
        return False
    return True


# --- player weapons -------------------------------------------------------


def _ability_mod(sheet: CharacterSheet, ability: str) -> int:
    return (sheet.abilities.get(ability, 10) - 10) // 2


def _codes(values: Any) -> set[str]:
    return {str(value).split("|")[0].upper() for value in values or []}


def _magic_bonus(raw: dict[str, Any] | None, name: str) -> int:
    if raw and raw.get("bonusWeapon"):
        try:
            return int(str(raw["bonusWeapon"]).replace(" ", ""))
        except ValueError:
            pass
    match = re.search(r"\+(\d)\b", name)
    return int(match.group(1)) if match else 0


def weapon_attack(
    sheet: CharacterSheet,
    *,
    name: str,
    raw: dict[str, Any] | None,
    two_handed: bool = False,
) -> Attack | None:
    """Attack profile of a weapon from its 5etools entry (proficiency assumed)."""
    if not raw or not raw.get("dmg1"):
        return None
    properties = _codes(raw.get("property"))
    ranged = str(raw.get("type") or "").split("|")[0].upper() == "R"
    strength = _ability_mod(sheet, "str")
    dexterity = _ability_mod(sheet, "dex")
    if ranged:
        modifier = dexterity
    elif "F" in properties:
        modifier = max(strength, dexterity)
    else:
        modifier = strength
    magic = _magic_bonus(raw, name)
    dice = str(raw.get("dmg2") if two_handed and raw.get("dmg2") else raw["dmg1"])
    bonus = modifier + magic
    damage = dice + (f"+{bonus}" if bonus > 0 else str(bonus) if bonus else "")
    return Attack(
        name=name,
        hit=modifier + proficiency_bonus(sheet.level) + magic,
        damage=[
            DamagePart(
                dice=damage,
                type=_WEAPON_DAMAGE_CODES.get(
                    str(raw.get("dmgType") or "").upper(), ""
                ),
            )
        ],
        ranged=ranged,
    )


def unarmed_attack(sheet: CharacterSheet) -> Attack:
    strength = _ability_mod(sheet, "str")
    return Attack(
        name="Mains nues",
        hit=strength + proficiency_bonus(sheet.level),
        damage=[DamagePart(dice=str(max(0, 1 + strength)), type="bludgeoning")],
    )


# --- resolution -----------------------------------------------------------

_ATTACKER_DISADVANTAGE = {"poisoned", "blinded", "restrained", "frightened", "prone"}
_TARGET_ADVANTAGE = {"blinded", "restrained", "stunned", "paralyzed", "unconscious"}
_AUTO_CRIT_MELEE = {"paralyzed", "unconscious"}


@dataclass
class AttackContext:
    attacker_conditions: set[str]
    target_conditions: set[str]
    requested: bool | None = None


def attack_advantage(
    attack: Attack, context: AttackContext
) -> tuple[bool | None, list[str]]:
    """Net advantage from the request and both sides' conditions, with reasons."""
    advantage_reasons: list[str] = []
    disadvantage_reasons: list[str] = []
    if context.requested is True:
        advantage_reasons.append("demandé")
    elif context.requested is False:
        disadvantage_reasons.append("demandé")
    for key in sorted(_ATTACKER_DISADVANTAGE & context.attacker_conditions):
        disadvantage_reasons.append(f"attaquant {key}")
    for key in sorted(_TARGET_ADVANTAGE & context.target_conditions):
        advantage_reasons.append(f"cible {key}")
    if "prone" in context.target_conditions:
        (disadvantage_reasons if attack.ranged else advantage_reasons).append(
            "cible prone"
        )
    notes = [f"⬆️ {reason}" for reason in advantage_reasons] + [
        f"⬇️ {reason}" for reason in disadvantage_reasons
    ]
    if advantage_reasons and disadvantage_reasons:
        return None, notes
    if advantage_reasons:
        return True, notes
    if disadvantage_reasons:
        return False, notes
    return None, notes


@dataclass
class DamageRoll:
    part: DamagePart
    rolled: int
    applied: int
    notation: str = ""
    note: str = ""


@dataclass
class AttackOutcome:
    attack: Attack
    roll: RollResult
    hit: bool | None
    critical: bool
    fumble: bool
    target_ac: int | None
    damage: list[DamageRoll] = field(default_factory=list)
    skipped: list[DamagePart] = field(default_factory=list)
    advantage_notes: list[str] = field(default_factory=list)

    @property
    def total_damage(self) -> int:
        return sum(item.applied for item in self.damage)


def _natural_d20(roll: RollResult) -> int:
    if roll.d20_pair is not None:
        return max(roll.d20_pair) if roll.advantage else min(roll.d20_pair)
    return roll.kept_rolls[0]


def roll_damage_part(
    part: DamagePart,
    *,
    critical: bool,
    resist: list[str],
    immune: list[str],
    vulnerable: list[str],
) -> DamageRoll:
    if part.dice.lstrip("+-").isdigit():
        # Flat damage (unarmed strike): nothing to roll, nothing to double.
        rolled, notation = max(0, int(part.dice)), ""
    else:
        dice = parse_dice(part.dice)
        if critical:
            dice = replace(
                dice,
                count=dice.count * 2,
                extra_dice=tuple(
                    replace(extra, count=extra.count * 2) for extra in dice.extra_dice
                ),
            )
        result = execute_roll(dice=dice, sheet=None, modifier_tokens=[], advantage=None)
        rolled, notation = max(0, result.total), result.dice_notation
    amount = rolled
    note = ""
    if part.type and part.type in immune:
        amount, note = 0, "immunité"
    elif part.type and part.type in resist:
        amount, note = amount // 2, "résistance"
    elif part.type and part.type in vulnerable:
        amount, note = amount * 2, "vulnérabilité"
    return DamageRoll(
        part=part, rolled=rolled, applied=amount, notation=notation, note=note
    )


def resolve_attack(
    attack: Attack,
    *,
    attacker_sheet: CharacterSheet | None,
    context: AttackContext,
    target_ac: int | None,
    hit_bonus: int = 0,
    resist: list[str] | None = None,
    immune: list[str] | None = None,
    vulnerable: list[str] | None = None,
) -> AttackOutcome:
    advantage, notes = attack_advantage(attack, context)
    # The sheet brings Bless, Halfling Lucky and inspiration to the d20.
    roll = execute_roll(
        dice=ParsedDice(count=1, sides=20, flat_modifier=attack.hit + hit_bonus),
        sheet=attacker_sheet,
        modifier_tokens=[],
        advantage=advantage,
        dc=target_ac,
    )
    natural = _natural_d20(roll)
    critical = natural == 20
    fumble = natural == 1
    if critical:
        hit: bool | None = True
    elif fumble:
        hit = False
    elif target_ac is None:
        hit = None
    else:
        hit = roll.total >= target_ac
    if hit and not attack.ranged and _AUTO_CRIT_MELEE & context.target_conditions:
        critical = True
        notes.append("💥 critique automatique (cible sans défense, au contact)")

    outcome = AttackOutcome(
        attack=attack,
        roll=roll,
        hit=hit,
        critical=critical,
        fumble=fumble,
        target_ac=target_ac,
        advantage_notes=notes,
    )
    if hit:
        had_advantage = roll.advantage is True
        for part in attack.damage:
            if part.needs_advantage and not had_advantage:
                outcome.skipped.append(part)
                continue
            outcome.damage.append(
                roll_damage_part(
                    part,
                    critical=critical,
                    resist=resist or [],
                    immune=immune or [],
                    vulnerable=vulnerable or [],
                )
            )
    return outcome


def format_damage_line(item: DamageRoll) -> str:
    kind = f" {damage_type_label(item.part.type)}" if item.part.type else ""
    rolled = f"`{item.notation}` → {item.rolled}" if item.notation else str(item.rolled)
    text = f"{rolled}{kind}"
    if item.note:
        text += f" ({item.note} : {item.applied})"
    return text
