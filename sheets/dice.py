import difflib
import random
import re
from collections import Counter
from dataclasses import dataclass, replace

import discord

from sheets.data import (
    ABILITIES,
    SKILL_ABILITIES,
    SKILL_ALIASES,
    CharacterSheet,
    fold_lookup_key,
    format_modifier,
    lookup_skill,
)

# A signed term after the main dice: `+5`, `-1`, `+1d4`, `-d6`.
_TERM = r"[+-](?:\d*d\d+|\d+)"
DICE_PATTERN = re.compile(
    rf"^(\d*)d(\d+)(?:r(\d+))?(?:(kh|kl)(\d+))?((?:{_TERM})*)$",
    re.IGNORECASE,
)
_BONUS_TERMS_PATTERN = re.compile(rf"^(?:{_TERM})+$", re.IGNORECASE)
_TERM_PATTERN = re.compile(r"([+-])(?:(\d*)d(\d+)|(\d+))", re.IGNORECASE)
# `d20 + 1d4 + 5` → `d20+1d4+5` (one token); `athletics + d4` → `athletics +d4`.
_SIGN_AFTER_NUMBER_PATTERN = re.compile(r"(?<=\d)\s*([+-])\s*(?=\d|d\d)", re.IGNORECASE)
_SPACE_AFTER_SIGN_PATTERN = re.compile(r"(?<!\S)([+-])\s+(?=\d|d\d)", re.IGNORECASE)
# `vs 15`, `dd15`, `DC 15`, `contre 15`.
_DC_WORDS = frozenset({"vs", "dd", "dc", "contre"})
_DC_GLUED_PATTERN = re.compile(r"^(?:vs|dd|dc)(\d+)$", re.IGNORECASE)
# `3x`, `x3`, `3×`.
_REPEAT_PATTERN = re.compile(r"^(?:(\d+)[x×]|[x×](\d+))$", re.IGNORECASE)
_CRIT_TOKENS = frozenset({"crit", "critique", "critical"})
_SECRET_TOKENS = frozenset({"secret", "cache", "prive"})
_ADVANTAGE_TOKENS = frozenset({"adv", "advantage", "avantage"})
_DISADVANTAGE_TOKENS = frozenset({"dis", "disadvantage", "desavantage", "desav"})
_MAX_DICE = 100
MAX_REPEAT = 10
_MAX_LABEL = 80

ABILITY_ALIASES: dict[str, str] = {
    "str": "str",
    "strength": "str",
    "for": "str",
    "force": "str",
    "dex": "dex",
    "dexterity": "dex",
    "dexterite": "dex",
    "agi": "dex",
    "agilite": "dex",
    "con": "con",
    "constitution": "con",
    "end": "con",
    "endurance": "con",
    "int": "int",
    "intelligence": "int",
    "wis": "wis",
    "wisdom": "wis",
    "sag": "wis",
    "sagesse": "wis",
    "cha": "cha",
    "charisma": "cha",
    "charisme": "cha",
}

ABILITY_LABELS_FR: dict[str, str] = {
    "str": "FOR",
    "dex": "DEX",
    "con": "CON",
    "int": "INT",
    "wis": "SAG",
    "cha": "CHA",
}

SKILL_LABELS_FR: dict[str, str] = {
    "acrobatics": "Acrobaties",
    "animal_handling": "Dressage",
    "arcana": "Arcanes",
    "athletics": "Athlétisme",
    "deception": "Tromperie",
    "history": "Histoire",
    "insight": "Intuition",
    "intimidation": "Intimidation",
    "investigation": "Investigation",
    "medicine": "Médecine",
    "nature": "Nature",
    "perception": "Perception",
    "performance": "Représentation",
    "persuasion": "Persuasion",
    "religion": "Religion",
    "sleight_of_hand": "Escamotage",
    "stealth": "Discrétion",
    "survival": "Survie",
}

_CONDITION_LABELS_FR: dict[str, str] = {
    "poisoned": "empoisonné",
    "frightened": "effrayé",
    "exhaustion": "épuisement",
}

_HALFLING_WORDS = ("halfelin", "halfling")


@dataclass(frozen=True)
class ExtraDice:
    """A dice group added to (sign 1) or taken from (sign -1) the main roll."""

    sign: int
    count: int
    sides: int

    @property
    def notation(self) -> str:
        return f"{'+' if self.sign > 0 else '-'}{self.count}d{self.sides}"


@dataclass(frozen=True)
class ParsedDice:
    count: int
    sides: int
    flat_modifier: int
    keep_mode: str | None = None
    keep_count: int = 0
    extra_dice: tuple[ExtraDice, ...] = ()
    # Reroll once any die of the main group showing this value or less (`2d6r2`).
    reroll_below: int = 0


@dataclass(frozen=True)
class RollResult:
    dice_notation: str
    dice_rolls: tuple[int, ...]
    kept_rolls: tuple[int, ...]
    flat_modifier: int
    sheet_modifier: int
    modifier_label: str
    total: int
    advantage: bool | None
    d20_pair: tuple[int, int] | None = None
    spent_inspiration: bool = False
    condition_note: str | None = None
    extra_rolls: tuple[tuple[ExtraDice, tuple[int, ...]], ...] = ()
    # (first face, rerolled face) for each die rerolled by `rN` or Lucky.
    rerolls: tuple[tuple[int, int], ...] = ()
    lucky_used: bool = False
    effect_notes: tuple[str, ...] = ()
    dc: int | None = None

    @property
    def success(self) -> bool | None:
        return None if self.dc is None else self.total >= self.dc


@dataclass(frozen=True)
class ParsedRollRequest:
    dice: ParsedDice
    modifier_tokens: list[str]
    advantage: bool | None
    dc: int | None = None
    repeat: int = 1
    label: str = ""
    crit: bool = False
    secret: bool = False


def _parse_terms(text: str | None) -> tuple[int, tuple[ExtraDice, ...]]:
    flat = 0
    extras: list[ExtraDice] = []
    for sign, count, sides, number in _TERM_PATTERN.findall(text or ""):
        factor = -1 if sign == "-" else 1
        if sides:
            extras.append(
                ExtraDice(sign=factor, count=int(count or 1), sides=int(sides))
            )
        else:
            flat += factor * int(number)
    return flat, tuple(extras)


def _check_dice_limits(dice: ParsedDice) -> None:
    groups = [(dice.count, dice.sides)] + [
        (extra.count, extra.sides) for extra in dice.extra_dice
    ]
    if any(count < 1 or sides < 1 for count, sides in groups):
        raise ValueError("Il faut au moins 1 dé, d’au moins 1 face.")
    if sum(count for count, _ in groups) > _MAX_DICE:
        raise ValueError(f"Pas plus de {_MAX_DICE} dés à la fois.")
    if dice.reroll_below and dice.reroll_below >= dice.sides:
        raise ValueError(
            f"`r{dice.reroll_below}` relancerait tous les résultats d’un d{dice.sides}."
        )


def parse_dice(notation: str) -> ParsedDice:
    match = DICE_PATTERN.match(notation.strip().lower())
    if not match:
        raise ValueError(
            f"Notation de dés invalide : `{notation}`. "
            "Exemples : `d20+5`, `1d20+1d4`, `2d6+3`, `4d6kh3`, `2d6r2`"
        )

    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    reroll_below = int(match.group(3) or 0)
    keep_mode = match.group(4).lower() if match.group(4) else None
    keep_count = int(match.group(5) or 0) if keep_mode else 0
    flat_modifier, extra_dice = _parse_terms(match.group(6))

    if keep_mode and (keep_count < 1 or keep_count >= count):
        raise ValueError(
            f"`{keep_mode}` doit garder entre 1 et {max(count - 1, 1)} dé(s) "
            f"sur {count}."
        )

    dice = ParsedDice(
        count=count,
        sides=sides,
        flat_modifier=flat_modifier,
        keep_mode=keep_mode,
        keep_count=keep_count,
        extra_dice=extra_dice,
        reroll_below=reroll_below,
    )
    _check_dice_limits(dice)
    return dice


def _split_advantage(tokens: list[str]) -> tuple[list[str], bool | None]:
    advantage: bool | None = None
    kept: list[str] = []
    for token in tokens:
        key = fold_lookup_key(token)
        if key in _ADVANTAGE_TOKENS:
            if advantage is False:
                raise ValueError(
                    "Impossible d’avoir avantage et désavantage à la fois."
                )
            advantage = True
            continue
        if key in _DISADVANTAGE_TOKENS:
            if advantage is True:
                raise ValueError(
                    "Impossible d’avoir avantage et désavantage à la fois."
                )
            advantage = False
            continue
        kept.append(token)
    return kept, advantage


def _split_dc(tokens: list[str]) -> tuple[list[str], int | None]:
    dc: int | None = None
    kept: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        glued = _DC_GLUED_PATTERN.match(token)
        value: str | None = None
        if glued:
            value = glued.group(1)
        elif fold_lookup_key(token) in _DC_WORDS:
            following = tokens[index + 1] if index + 1 < len(tokens) else ""
            if not following.isdigit():
                raise ValueError(f"Il manque le DD après `{token}`. Exemple : `vs 15`")
            value = following
            index += 1
        if value is None:
            kept.append(token)
        else:
            if dc is not None:
                raise ValueError("Un seul DD par jet.")
            dc = int(value)
        index += 1
    return kept, dc


def _split_flags(tokens: list[str]) -> tuple[list[str], int, bool, bool]:
    repeat = 1
    crit = False
    secret = False
    kept: list[str] = []
    for token in tokens:
        key = fold_lookup_key(token)
        repeat_match = _REPEAT_PATTERN.match(token)
        if repeat_match:
            repeat = int(repeat_match.group(1) or repeat_match.group(2))
            if not 1 <= repeat <= MAX_REPEAT:
                raise ValueError(f"Entre 1 et {MAX_REPEAT} jets à la fois.")
        elif key in _CRIT_TOKENS:
            crit = True
        elif key in _SECRET_TOKENS:
            secret = True
        else:
            kept.append(token)
    return kept, repeat, crit, secret


def _double_for_crit(dice: ParsedDice) -> ParsedDice:
    if dice.keep_mode:
        raise ValueError("`crit` ne marche pas avec `kh`/`kl`.")
    doubled = replace(
        dice,
        count=dice.count * 2,
        extra_dice=tuple(
            replace(extra, count=extra.count * 2) for extra in dice.extra_dice
        ),
    )
    _check_dice_limits(doubled)
    return doubled


def parse_roll_args(args: str) -> ParsedRollRequest:
    body, _, label = args.partition("#")
    label = " ".join(label.split())[:_MAX_LABEL]
    text = _SIGN_AFTER_NUMBER_PATTERN.sub(r"\1", body)
    tokens = _SPACE_AFTER_SIGN_PATTERN.sub(r"\1", text).split()
    if not tokens:
        raise ValueError(
            "Il manque le jet. Exemples : `d20+5`, `adv athlétisme`, `2d6+3`"
        )

    tokens, advantage = _split_advantage(tokens)
    tokens, dc = _split_dc(tokens)
    tokens, repeat, crit, secret = _split_flags(tokens)
    # Bare `+2` / `-1` / `+1d4` tokens are added on top of whatever is rolled
    # (a d20 when nothing else is given), e.g. `athletics +d4` for Guidance.
    bonus_terms = "".join(t for t in tokens if _BONUS_TERMS_PATTERN.match(t))
    flat_bonus, bonus_dice = _parse_terms(bonus_terms)
    tokens = [t for t in tokens if not _BONUS_TERMS_PATTERN.match(t)]

    dice_index = next(
        (
            index
            for index, token in enumerate(tokens)
            if DICE_PATTERN.match(token.lower())
        ),
        None,
    )
    if dice_index is None:
        if crit:
            raise ValueError("Précise les dés de dégâts : `crit 2d6+3`")
        dice = ParsedDice(count=1, sides=20, flat_modifier=0)
        modifier_tokens = tokens
    else:
        dice = parse_dice(tokens[dice_index])
        modifier_tokens = tokens[:dice_index] + tokens[dice_index + 1 :]
    if flat_bonus or bonus_dice:
        dice = replace(
            dice,
            flat_modifier=dice.flat_modifier + flat_bonus,
            extra_dice=dice.extra_dice + bonus_dice,
        )
        _check_dice_limits(dice)
    if crit:
        dice = _double_for_crit(dice)
    return ParsedRollRequest(
        dice=dice,
        modifier_tokens=modifier_tokens,
        advantage=advantage,
        dc=dc,
        repeat=repeat,
        label=label,
        crit=crit,
        secret=secret,
    )


def parse_advantage_flag(text: str | None) -> bool | None:
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    kept, advantage = _split_advantage([raw])
    if kept or advantage is None:
        raise ValueError("L’avantage doit être `avantage` ou `désavantage`.")
    return advantage


def parse_bonus(bonus: int | str | None) -> tuple[int, tuple[ExtraDice, ...]]:
    """Parse the `/roll bonus` option: `2`, `-1`, `1d4`, `+1d4+2`."""
    if bonus is None:
        return 0, ()
    if isinstance(bonus, int):
        return bonus, ()
    text = "".join(str(bonus).split())
    if not text:
        return 0, ()
    if text[0] not in "+-":
        text = f"+{text}"
    if not _BONUS_TERMS_PATTERN.match(text):
        raise ValueError(
            f"Bonus invalide : `{bonus}`. Exemples : `2`, `-1`, `1d4`, `1d4+2`"
        )
    return _parse_terms(text)


def apply_roll_options(
    request: ParsedRollRequest,
    *,
    bonus: int | str | None = None,
    advantage: bool | None = None,
) -> ParsedRollRequest:
    merged = request.advantage
    if advantage is not None:
        if merged is not None and merged != advantage:
            raise ValueError("Impossible d’avoir avantage et désavantage à la fois.")
        merged = advantage
    flat, extras = parse_bonus(bonus)
    dice = request.dice
    if flat or extras:
        dice = replace(
            dice,
            flat_modifier=dice.flat_modifier + flat,
            extra_dice=dice.extra_dice + extras,
        )
        _check_dice_limits(dice)
    return replace(request, dice=dice, advantage=merged)


def validate_roll_request(request: ParsedRollRequest) -> None:
    if request.advantage is not None and not (
        request.dice.count == 1 and request.dice.sides == 20
    ):
        raise ValueError("L’avantage et le désavantage ne marchent qu’avec un `d20`.")


def _match_skill(text: str) -> str | None:
    return lookup_skill(text)


def _match_ability(text: str) -> str | None:
    token = fold_lookup_key(text)
    if token in ABILITIES:
        return token
    return ABILITY_ALIASES.get(token)


def _suggestion_candidates() -> dict[str, str]:
    """Folded key → what to suggest typing."""
    candidates: dict[str, str] = {}
    for alias, skill in SKILL_ALIASES.items():
        candidates[alias] = SKILL_LABELS_FR.get(skill, alias).lower()
    for skill in SKILL_ABILITIES:
        candidates.setdefault(skill, skill.replace("_", " "))
    for alias in ABILITY_ALIASES:
        candidates.setdefault(alias, alias)
    return candidates


def suggest_modifier(text: str) -> str | None:
    candidates = _suggestion_candidates()
    matches = difflib.get_close_matches(
        fold_lookup_key(text), list(candidates), n=1, cutoff=0.7
    )
    return candidates[matches[0]] if matches else None


def _unknown_modifier_error(text: str) -> ValueError:
    suggestion = suggest_modifier(text)
    hint = f" Tu voulais dire `{suggestion}` ?" if suggestion else ""
    return ValueError(
        f"Je ne connais pas `{text}`.{hint}\n"
        "Utilise une caractéristique (`force`, `dex`), une compétence "
        "(`athlétisme`, `discrétion`) ou une sauvegarde (`sauvegarde sag`, `dex save`). "
        "Un texte libre se met après `#` : `d20+5 # épée longue`."
    )


def _save_label(ability: str, modifier: int) -> str:
    return f"Sauvegarde {ABILITY_LABELS_FR[ability]} ({format_modifier(modifier)})"


def resolve_sheet_modifier(
    sheet: CharacterSheet | None, tokens: list[str]
) -> tuple[int, str]:
    if not tokens:
        return 0, ""

    if sheet is None:
        raise ValueError(
            "Il faut une fiche de personnage pour les jets de caractéristique, "
            "de compétence ou de sauvegarde. Lance les dés à la main "
            "(`d20+5`) ou crée une fiche."
        )

    text = " ".join(tokens).lower().strip()
    normalized = fold_lookup_key(text)

    if "save" in normalized or "sauvegarde" in normalized:
        for ability in ABILITIES:
            if (
                ability in normalized.split("_")
                or ability in text.split()
                or ABILITY_ALIASES.get(text.split()[0]) == ability
            ):
                modifier = sheet.get_save_modifier(ability)
                return modifier, _save_label(ability, modifier)

        for alias, ability in ABILITY_ALIASES.items():
            if alias in normalized:
                modifier = sheet.get_save_modifier(ability)
                return modifier, _save_label(ability, modifier)

        raise ValueError(
            "Sauvegarde inconnue. Exemples : `sauvegarde dex`, `dex save`, `save sag`"
        )

    skill = _match_skill(text)
    if skill:
        modifier = sheet.get_skill_modifier(skill)
        label = SKILL_LABELS_FR.get(skill, skill.replace("_", " ").title())
        if skill in sheet.skill_expertise:
            label = f"{label} (expertise)"
        elif skill in sheet.skill_proficiencies:
            label = f"{label} (maîtrise)"
        return modifier, f"{label} ({format_modifier(modifier)})"

    ability = _match_ability(text.replace("_", " "))
    if ability:
        score = sheet.abilities[ability]
        modifier = (score - 10) // 2
        return modifier, f"{ABILITY_LABELS_FR[ability]} ({format_modifier(modifier)})"

    raise _unknown_modifier_error(" ".join(tokens))


def _is_saving_throw(tokens: list[str]) -> bool:
    if not tokens:
        return False
    normalized = fold_lookup_key(" ".join(tokens))
    return "save" in normalized or "sauvegarde" in normalized


def _is_ability_check(tokens: list[str]) -> bool:
    if not tokens or _is_saving_throw(tokens):
        return False
    text = " ".join(tokens)
    return (
        _match_skill(text) is not None
        or _match_ability(text.replace("_", " ")) is not None
    )


def is_halfling(sheet: CharacterSheet | None) -> bool:
    if sheet is None:
        return False
    species = fold_lookup_key(sheet.species)
    return any(word in species for word in _HALFLING_WORDS)


def _roll_die(sides: int, reroll_below: int, rerolls: list[tuple[int, int]]) -> int:
    face = random.randint(1, sides)
    if face <= reroll_below:
        new_face = random.randint(1, sides)
        rerolls.append((face, new_face))
        return new_face
    return face


def _sheet_d20_effects(
    sheet: CharacterSheet | None, modifier_tokens: list[str]
) -> tuple[tuple[ExtraDice, ...], tuple[str, ...]]:
    """Bless (+1d4) / Bane (-1d4) on attack rolls and saves, not ability checks."""
    from sheets.conditions import sheet_condition_keys

    if sheet is None or _is_ability_check(modifier_tokens):
        return (), ()
    keys = sheet_condition_keys(sheet)
    extras: list[ExtraDice] = []
    notes: list[str] = []
    if "blessed" in keys:
        extras.append(ExtraDice(sign=1, count=1, sides=4))
        notes.append("🙏 Bénédiction +1d4")
    if "baned" in keys:
        extras.append(ExtraDice(sign=-1, count=1, sides=4))
        notes.append("🪦 Fléau -1d4")
    return tuple(extras), tuple(notes)


def format_dice_notation(dice: ParsedDice) -> str:
    notation = f"{dice.count}d{dice.sides}"
    if dice.reroll_below:
        notation += f"r{dice.reroll_below}"
    if dice.keep_mode:
        notation += f"{dice.keep_mode}{dice.keep_count}"
    notation += "".join(extra.notation for extra in dice.extra_dice)
    if dice.flat_modifier > 0:
        notation += f"+{dice.flat_modifier}"
    elif dice.flat_modifier < 0:
        notation += str(dice.flat_modifier)
    return notation


def execute_roll(
    *,
    dice: ParsedDice,
    sheet: CharacterSheet | None,
    modifier_tokens: list[str],
    advantage: bool | None,
    dc: int | None = None,
) -> RollResult:
    from sheets.conditions import ability_check_disadvantage_source

    sheet_modifier, modifier_label = resolve_sheet_modifier(sheet, modifier_tokens)
    total_modifier = dice.flat_modifier + sheet_modifier
    requested = advantage
    condition_note: str | None = None
    spent_inspiration = False

    if sheet is not None and _is_ability_check(modifier_tokens):
        source = ability_check_disadvantage_source(sheet)
        if source:
            condition_note = source
            if advantage is True:
                advantage = None
            else:
                advantage = False

    is_d20 = dice.count == 1 and dice.sides == 20
    if sheet is not None and sheet.inspired and is_d20:
        if requested is True:
            pass
        elif advantage is False:
            advantage = None
            spent_inspiration = True
            sheet.inspired = False
        elif advantage is None:
            advantage = True
            spent_inspiration = True
            sheet.inspired = False

    effect_notes: tuple[str, ...] = ()
    if is_d20:
        effect_dice, effect_notes = _sheet_d20_effects(sheet, modifier_tokens)
        if effect_dice:
            dice = replace(dice, extra_dice=dice.extra_dice + effect_dice)

    lucky = is_d20 and is_halfling(sheet)
    reroll_below = max(dice.reroll_below, 1) if lucky else dice.reroll_below
    rerolls: list[tuple[int, int]] = []

    d20_pair: tuple[int, int] | None = None
    if advantage is not None and is_d20:
        first = _roll_die(20, reroll_below, rerolls)
        second = _roll_die(20, reroll_below, rerolls)
        d20_pair = (first, second)
        chosen = max(first, second) if advantage else min(first, second)
        dice_rolls = (chosen,)
    else:
        dice_rolls = tuple(
            _roll_die(dice.sides, reroll_below, rerolls) for _ in range(dice.count)
        )

    kept_rolls = dice_rolls
    if dice.keep_mode and dice.keep_count:
        if dice.keep_mode == "kh":
            kept_rolls = tuple(sorted(dice_rolls, reverse=True)[: dice.keep_count])
        else:
            kept_rolls = tuple(sorted(dice_rolls)[: dice.keep_count])

    extra_rolls = tuple(
        (extra, tuple(random.randint(1, extra.sides) for _ in range(extra.count)))
        for extra in dice.extra_dice
    )
    extra_total = sum(extra.sign * sum(rolls) for extra, rolls in extra_rolls)

    total = sum(kept_rolls) + extra_total + total_modifier
    return RollResult(
        dice_notation=format_dice_notation(dice),
        dice_rolls=dice_rolls,
        kept_rolls=kept_rolls,
        flat_modifier=dice.flat_modifier,
        sheet_modifier=sheet_modifier,
        modifier_label=modifier_label,
        total=total,
        advantage=advantage,
        d20_pair=d20_pair,
        spent_inspiration=spent_inspiration,
        condition_note=condition_note,
        extra_rolls=extra_rolls,
        rerolls=tuple(rerolls),
        lucky_used=lucky and bool(rerolls),
        effect_notes=effect_notes,
        dc=dc,
    )


ROLL_COLOR = 0xD4A017
ROLL_ADV_COLOR = 0x2980B9
ROLL_DIS_COLOR = 0x7F8C8D
ROLL_NAT20_COLOR = 0x27AE60
ROLL_NAT1_COLOR = 0xC0392B
CRIT_SUCCESS_LABEL = "🌟 Critique"
CRIT_FAIL_LABEL = "💀 Échec critique"
ROLLS_FIELD = "🎲 Dés"
BREAKDOWN_FIELD = "🧮 Calcul"
MODIFIER_FIELD = "➕ Modificateur"

_KEEP_PATTERN = re.compile(r"(kh|kl)(\d+)", re.IGNORECASE)
# Only the main dice group counts for crits: `1d4+1d20` is not a d20 roll.
_MAIN_D20_PATTERN = re.compile(r"^\d*d20(?!\d)", re.IGNORECASE)


def _effective_d20(result: RollResult) -> int | None:
    if result.d20_pair is not None:
        return max(result.d20_pair) if result.advantage else min(result.d20_pair)
    if len(result.kept_rolls) == 1 and _MAIN_D20_PATTERN.match(result.dice_notation):
        return result.kept_rolls[0]
    return None


def d20_crit_kind(face: int | None) -> str | None:
    if face == 20:
        return "success"
    if face == 1:
        return "fail"
    return None


def format_d20_face(face: int) -> str:
    if face == 20:
        return f"{CRIT_SUCCESS_LABEL} **20**"
    if face == 1:
        return f"{CRIT_FAIL_LABEL} **1**"
    return f"**{face}**"


def _roll_embed_color(result: RollResult) -> int:
    d20 = _effective_d20(result)
    if d20 == 20:
        return ROLL_NAT20_COLOR
    if d20 == 1:
        return ROLL_NAT1_COLOR
    if result.advantage is True:
        return ROLL_ADV_COLOR
    if result.advantage is False:
        return ROLL_DIS_COLOR
    return ROLL_COLOR


def _format_modifier_breakdown(result: RollResult) -> str | None:
    if not result.flat_modifier and not result.sheet_modifier:
        return None
    parts: list[str] = []
    if result.flat_modifier:
        parts.append(format_modifier(result.flat_modifier))
    if result.sheet_modifier:
        parts.append(result.modifier_label or format_modifier(result.sheet_modifier))
    return " · ".join(parts)


def _dropped_rolls(result: RollResult) -> list[int]:
    remaining = Counter(result.kept_rolls)
    dropped: list[int] = []
    for value in result.dice_rolls:
        if remaining[value]:
            remaining[value] -= 1
        else:
            dropped.append(value)
    return dropped


def _format_roll_values(result: RollResult) -> str:
    lines = [_format_main_rolls(result)]
    for extra, rolls in result.extra_rolls:
        values = " · ".join(str(value) for value in rolls)
        if len(rolls) > 1:
            values += f" = {sum(rolls)}"
        lines.append(f"{extra.notation[0]} {extra.notation[1:]} : **{values}**")
    if result.rerolls:
        rerolled = ", ".join(f"~~{old}~~ → {new}" for old, new in result.rerolls)
        prefix = "🍀 Chanceux" if result.lucky_used else "🔁 Relancé"
        lines.append(f"{prefix} : {rerolled}")
    return "\n".join(lines)


def _format_main_rolls(result: RollResult) -> str:
    if result.d20_pair is not None:
        kept = max(result.d20_pair) if result.advantage else min(result.d20_pair)
        dropped = min(result.d20_pair) if result.advantage else max(result.d20_pair)
        mode = "⬆️ Avantage" if result.advantage else "⬇️ Désavantage"
        return f"{mode}\n{format_d20_face(kept)} gardé · ~~{dropped}~~ écarté"

    if result.kept_rolls != result.dice_rolls:
        keep_match = _KEEP_PATTERN.search(result.dice_notation)
        label = (
            "Meilleurs gardés"
            if keep_match and keep_match.group(1).lower() == "kh"
            else "Plus faibles gardés"
        )
        rolled = ", ".join(str(value) for value in result.dice_rolls)
        kept = ", ".join(str(value) for value in result.kept_rolls)
        return f"🎯 {label}\n{rolled} → **{kept}**"

    if len(result.dice_rolls) == 1:
        face = result.dice_rolls[0]
        if _effective_d20(result) == face:
            return format_d20_face(face)
        return f"**{face}**"

    if len(result.dice_rolls) <= 8:
        return " · ".join(str(value) for value in result.dice_rolls)

    return ", ".join(str(value) for value in result.dice_rolls)


def _format_roll_breakdown(result: RollResult) -> str | None:
    parts = [str(sum(result.kept_rolls))]
    for extra, rolls in result.extra_rolls:
        parts.append(f"{'+' if extra.sign > 0 else '-'} {sum(rolls)}")
    modifier = result.flat_modifier + result.sheet_modifier
    if modifier:
        parts.append(f"{'+' if modifier > 0 else '-'} {abs(modifier)}")
    if len(parts) == 1:
        return None
    return f"{' '.join(parts)} = **{result.total}**"


def format_dc_verdict(result: RollResult) -> str | None:
    if result.dc is None:
        return None
    if result.success:
        return f"✅ Réussite (DD {result.dc})"
    return f"❌ Échec (DD {result.dc})"


def _footer_parts(results: list[RollResult]) -> list[str]:
    parts: list[str] = []
    for result in results:
        if result.condition_note:
            note = _CONDITION_LABELS_FR.get(
                result.condition_note, result.condition_note
            )
            parts.append(f"⬇️ Désavantage ({note})")
        parts.extend(result.effect_notes)
        if result.spent_inspiration:
            parts.append("✨ Inspiration dépensée")
    return list(dict.fromkeys(parts))


def _title_with_label(base: str, label: str) -> str:
    return f"{base} · {label}" if label else base


def format_roll_embed(
    result: RollResult, *, roller_label: str, label: str = ""
) -> discord.Embed:
    clean_label = roller_label.replace("**", "").strip()
    d20 = _effective_d20(result)
    crit = d20_crit_kind(d20)
    if crit == "success":
        title = f"{CRIT_SUCCESS_LABEL} — {clean_label}"
        description = f"**20** sur le d20\nTotal **{result.total}**"
    elif crit == "fail":
        title = f"{CRIT_FAIL_LABEL} — {clean_label}"
        description = f"**1** sur le d20\nTotal **{result.total}**"
    else:
        title = f"🎲 {clean_label}"
        description = f"**{result.total}**"
    verdict = format_dc_verdict(result)
    if verdict:
        description += f"\n{verdict}"
    embed = discord.Embed(
        title=_title_with_label(title, label),
        description=description,
        color=_roll_embed_color(result),
    )
    embed.add_field(name="🎯 Notation", value=f"`{result.dice_notation}`", inline=True)
    embed.add_field(name=ROLLS_FIELD, value=_format_roll_values(result), inline=False)

    modifier = _format_modifier_breakdown(result)
    if modifier:
        embed.add_field(name=MODIFIER_FIELD, value=modifier, inline=True)

    breakdown = _format_roll_breakdown(result)
    if breakdown:
        embed.add_field(name=BREAKDOWN_FIELD, value=breakdown, inline=False)

    footer_parts = _footer_parts([result])
    if footer_parts:
        embed.set_footer(text=" · ".join(footer_parts))
    return embed


def _compact_values(result: RollResult) -> str:
    if result.d20_pair is not None:
        kept = max(result.d20_pair) if result.advantage else min(result.d20_pair)
        dropped = min(result.d20_pair) if result.advantage else max(result.d20_pair)
        text = f"{kept} ~~{dropped}~~"
    else:
        text = " · ".join(str(value) for value in result.kept_rolls)
        dropped_values = _dropped_rolls(result)
        if dropped_values:
            text += " " + " ".join(f"~~{value}~~" for value in dropped_values)
    for extra, rolls in result.extra_rolls:
        text += f" {extra.notation[0]} ({' · '.join(str(v) for v in rolls)})"
    return text


def _series_line(index: int, result: RollResult) -> str:
    crit = d20_crit_kind(_effective_d20(result))
    marker = {"success": " 🌟", "fail": " 💀"}.get(crit or "", "")
    line = f"`{index}.` **{result.total}**{marker} — {_compact_values(result)}"
    verdict = format_dc_verdict(result)
    if verdict:
        line += f" · {verdict}"
    return line


def format_roll_series_embed(
    results: list[RollResult], *, roller_label: str, label: str = ""
) -> discord.Embed:
    """One embed for `3x d20+5`-style repeated rolls."""
    if len(results) == 1:
        return format_roll_embed(results[0], roller_label=roller_label, label=label)
    clean_label = roller_label.replace("**", "").strip()
    first = results[0]
    lines = [_series_line(index, result) for index, result in enumerate(results, 1)]
    embed = discord.Embed(
        title=_title_with_label(f"🎲 {clean_label} — {len(results)} jets", label),
        description="\n".join(lines),
        color=ROLL_COLOR,
    )
    embed.add_field(name="🎯 Notation", value=f"`{first.dice_notation}`", inline=True)
    modifier = _format_modifier_breakdown(first)
    if modifier:
        embed.add_field(name=MODIFIER_FIELD, value=modifier, inline=True)
    if first.dc is not None:
        successes = sum(1 for result in results if result.success)
        embed.add_field(
            name="✅ Réussites", value=f"{successes}/{len(results)}", inline=True
        )
    else:
        embed.add_field(
            name="Σ Somme", value=str(sum(r.total for r in results)), inline=True
        )
    footer_parts = _footer_parts(results)
    if any(result.lucky_used for result in results):
        footer_parts.append("🍀 Chanceux")
    elif any(result.rerolls for result in results):
        footer_parts.append("🔁 Relances appliquées")
    if footer_parts:
        embed.set_footer(text=" · ".join(footer_parts))
    return embed
