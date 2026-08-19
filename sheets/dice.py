import random
import re
from dataclasses import dataclass

import discord

from sheets.data import ABILITIES, SKILL_ABILITIES, CharacterSheet, format_modifier

DICE_PATTERN = re.compile(
    r"^(\d+)d(\d+)(?:(kh|kl)(\d+))?([+-]\d+)?$",
    re.IGNORECASE,
)
ABILITY_ALIASES: dict[str, str] = {
    "str": "str",
    "strength": "str",
    "for": "str",
    "force": "str",
    "dex": "dex",
    "dexterity": "dex",
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


@dataclass(frozen=True)
class ParsedDice:
    count: int
    sides: int
    flat_modifier: int
    keep_mode: str | None = None
    keep_count: int = 0


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


@dataclass(frozen=True)
class ParsedRollRequest:
    dice: ParsedDice
    modifier_tokens: list[str]
    advantage: bool | None


def parse_dice(notation: str) -> ParsedDice:
    match = DICE_PATTERN.match(notation.strip().lower())
    if not match:
        raise ValueError(f"Invalid dice notation: `{notation}`. Example: `1d20`, `2d6+3`, `2d20kh1`")

    count = int(match.group(1))
    sides = int(match.group(2))
    keep_mode = match.group(3).lower() if match.group(3) else None
    keep_count = int(match.group(4) or 0) if keep_mode else 0
    flat_modifier = int(match.group(5) or 0)

    if count < 1 or sides < 1:
        raise ValueError("Dice count and sides must be at least 1.")
    if count > 100:
        raise ValueError("Cannot roll more than 100 dice at once.")
    if keep_mode and (keep_count < 1 or keep_count >= count):
        raise ValueError("Keep highest/lowest requires kh/kl count between 1 and dice count - 1.")

    return ParsedDice(
        count=count,
        sides=sides,
        flat_modifier=flat_modifier,
        keep_mode=keep_mode,
        keep_count=keep_count,
    )


def parse_roll_args(args: str) -> ParsedRollRequest:
    tokens = args.split()
    if not tokens:
        raise ValueError("Missing roll. Example: `1d20`, `adv 1d20 athletics`, `2d6+3`")

    advantage: bool | None = None
    if tokens[0].lower() in {"adv", "advantage"}:
        advantage = True
        tokens = tokens[1:]
    elif tokens[0].lower() in {"dis", "disadvantage"}:
        advantage = False
        tokens = tokens[1:]

    if not tokens:
        raise ValueError("Missing dice or modifier after advantage/disadvantage.")

    dice_index = next((index for index, token in enumerate(tokens) if DICE_PATTERN.match(token.lower())), None)
    if dice_index is None:
        return ParsedRollRequest(
            dice=ParsedDice(count=1, sides=20, flat_modifier=0),
            modifier_tokens=tokens,
            advantage=advantage,
        )

    dice = parse_dice(tokens[dice_index])
    modifier_tokens = tokens[:dice_index] + tokens[dice_index + 1 :]
    return ParsedRollRequest(dice=dice, modifier_tokens=modifier_tokens, advantage=advantage)


def validate_roll_request(request: ParsedRollRequest) -> None:
    if request.advantage is not None and not (
        request.dice.count == 1 and request.dice.sides == 20
    ):
        raise ValueError("Advantage/disadvantage only works with `1d20` rolls.")


def _format_skill_name(skill: str) -> str:
    return skill.replace("_", " ").title()


def _match_skill(text: str) -> str | None:
    normalized = text.lower().replace("-", " ").strip()
    underscored = normalized.replace(" ", "_")
    if underscored in SKILL_ABILITIES:
        return underscored

    for skill in SKILL_ABILITIES:
        if skill.replace("_", " ") == normalized:
            return skill
    return None


def _match_ability(text: str) -> str | None:
    token = text.lower().strip()
    if token in ABILITIES:
        return token
    return ABILITY_ALIASES.get(token)


def resolve_sheet_modifier(sheet: CharacterSheet | None, tokens: list[str]) -> tuple[int, str]:
    if not tokens:
        return 0, ""

    if sheet is None:
        raise ValueError(
            "A character sheet is required for ability, skill or save rolls. "
            "Use plain dice like `1d20+5`, or create a sheet first."
        )

    text = " ".join(tokens).lower().strip()
    normalized = text.replace("-", " ").replace(" ", "_")

    if "save" in normalized or "sauvegarde" in normalized:
        for ability in ABILITIES:
            if (
                ability in normalized.split("_")
                or ability in text.split()
                or ABILITY_ALIASES.get(text.split()[0]) == ability
            ):
                modifier = sheet.get_save_modifier(ability)
                return modifier, f"{ability.upper()} save ({format_modifier(modifier)})"

        for alias, ability in ABILITY_ALIASES.items():
            if alias in normalized:
                modifier = sheet.get_save_modifier(ability)
                return modifier, f"{ability.upper()} save ({format_modifier(modifier)})"

        raise ValueError("Unknown saving throw. Example: `dex save`, `save wis`")

    skill = _match_skill(text)
    if skill:
        modifier = sheet.get_skill_modifier(skill)
        label = _format_skill_name(skill)
        if skill in sheet.skill_expertise:
            label = f"{label} (expertise)"
        elif skill in sheet.skill_proficiencies:
            label = f"{label} (proficient)"
        return modifier, f"{label} ({format_modifier(modifier)})"

    ability = _match_ability(text.replace("_", " "))
    if ability:
        score = sheet.abilities[ability]
        modifier = (score - 10) // 2
        return modifier, f"{ability.upper()} ({format_modifier(modifier)})"

    raise ValueError(
        "Unknown modifier. Use an ability (`str`), skill (`athletics`) or save (`dex save`)."
    )


def execute_roll(
    *,
    dice: ParsedDice,
    sheet: CharacterSheet | None,
    modifier_tokens: list[str],
    advantage: bool | None,
) -> RollResult:
    sheet_modifier, modifier_label = resolve_sheet_modifier(sheet, modifier_tokens)
    total_modifier = dice.flat_modifier + sheet_modifier

    dice_notation = f"{dice.count}d{dice.sides}"
    if dice.keep_mode:
        dice_notation += f"{dice.keep_mode}{dice.keep_count}"
    if dice.flat_modifier > 0:
        dice_notation += f"+{dice.flat_modifier}"
    elif dice.flat_modifier < 0:
        dice_notation += str(dice.flat_modifier)

    d20_pair: tuple[int, int] | None = None
    if advantage is not None and dice.count == 1 and dice.sides == 20:
        first = random.randint(1, 20)
        second = random.randint(1, 20)
        d20_pair = (first, second)
        chosen = max(first, second) if advantage else min(first, second)
        dice_rolls = (chosen,)
    else:
        dice_rolls = tuple(random.randint(1, dice.sides) for _ in range(dice.count))

    kept_rolls = dice_rolls
    if dice.keep_mode and dice.keep_count:
        if dice.keep_mode == "kh":
            kept_rolls = tuple(sorted(dice_rolls, reverse=True)[: dice.keep_count])
        else:
            kept_rolls = tuple(sorted(dice_rolls)[: dice.keep_count])

    total = sum(kept_rolls) + total_modifier
    return RollResult(
        dice_notation=dice_notation,
        dice_rolls=dice_rolls,
        kept_rolls=kept_rolls,
        flat_modifier=dice.flat_modifier,
        sheet_modifier=sheet_modifier,
        modifier_label=modifier_label,
        total=total,
        advantage=advantage,
        d20_pair=d20_pair,
    )


ROLL_COLOR = 0xD4A017
ROLL_ADV_COLOR = 0x2980B9
ROLL_DIS_COLOR = 0x7F8C8D
ROLL_NAT20_COLOR = 0x27AE60
ROLL_NAT1_COLOR = 0xC0392B

_KEEP_PATTERN = re.compile(r"(kh|kl)(\d+)", re.IGNORECASE)


def _effective_d20(result: RollResult) -> int | None:
    if result.d20_pair is not None:
        return max(result.d20_pair) if result.advantage else min(result.d20_pair)
    if len(result.kept_rolls) == 1 and "d20" in result.dice_notation.lower():
        return result.kept_rolls[0]
    return None


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


def _format_roll_values(result: RollResult) -> str:
    if result.d20_pair is not None:
        kept = max(result.d20_pair) if result.advantage else min(result.d20_pair)
        dropped = min(result.d20_pair) if result.advantage else max(result.d20_pair)
        mode = "⬆️ Advantage" if result.advantage else "⬇️ Disadvantage"
        return f"{mode}\n**{kept}** kept · ~~{dropped}~~ dropped"

    if result.kept_rolls != result.dice_rolls:
        keep_match = _KEEP_PATTERN.search(result.dice_notation)
        label = "Keep highest" if keep_match and keep_match.group(1).lower() == "kh" else "Keep lowest"
        rolled = ", ".join(str(value) for value in result.dice_rolls)
        kept = ", ".join(str(value) for value in result.kept_rolls)
        return f"🎯 {label}\n{rolled} → **{kept}**"

    if len(result.dice_rolls) == 1:
        return f"**{result.dice_rolls[0]}**"

    if len(result.dice_rolls) <= 8:
        return " · ".join(str(value) for value in result.dice_rolls)

    return ", ".join(str(value) for value in result.dice_rolls)


def _format_roll_breakdown(result: RollResult) -> str | None:
    dice_sum = sum(result.kept_rolls)
    modifier = result.flat_modifier + result.sheet_modifier
    if modifier == 0 and dice_sum == result.total:
        return None
    mod_text = format_modifier(modifier)
    return f"{dice_sum} {mod_text} = **{result.total}**"


def format_roll_embed(result: RollResult, *, roller_label: str) -> discord.Embed:
    clean_label = roller_label.replace("**", "").strip()
    embed = discord.Embed(
        title=f"🎲 {clean_label}",
        description=f"**{result.total}**",
        color=_roll_embed_color(result),
    )
    embed.add_field(name="🎯 Notation", value=f"`{result.dice_notation}`", inline=True)
    embed.add_field(name="🎲 Rolls", value=_format_roll_values(result), inline=False)

    modifier = _format_modifier_breakdown(result)
    if modifier:
        embed.add_field(name="➕ Modifier", value=modifier, inline=True)

    breakdown = _format_roll_breakdown(result)
    if breakdown:
        embed.add_field(name="🧮 Breakdown", value=breakdown, inline=False)

    d20 = _effective_d20(result)
    if d20 == 20:
        embed.set_footer(text="🌟 Natural 20!")
    elif d20 == 1:
        embed.set_footer(text="💀 Natural 1!")
    return embed


def format_roll_result(result: RollResult, *, roller_label: str) -> str:
    dice_part = ", ".join(str(value) for value in result.dice_rolls)
    lines = [f"🎲 {roller_label} — `{result.dice_notation}`"]

    if result.modifier_label:
        lines[0] += f" · {result.modifier_label}"

    detail = f"**{result.total}**"
    if result.d20_pair is not None:
        kept, dropped = (
            (max(result.d20_pair), min(result.d20_pair))
            if result.advantage
            else (min(result.d20_pair), max(result.d20_pair))
        )
        mode = "⬆️ advantage" if result.advantage else "⬇️ disadvantage"
        detail += f" · d20 **{kept}** kept, ~~{dropped}~~ dropped ({mode})"
    elif result.kept_rolls != result.dice_rolls:
        kept = ", ".join(str(value) for value in result.kept_rolls)
        detail += f" · rolled {dice_part} → kept **{kept}**"
    elif len(result.dice_rolls) == 1:
        sides_match = re.search(r"d(\d+)", result.dice_notation, re.IGNORECASE)
        sides_label = sides_match.group(1) if sides_match else "?"
        detail += f" · d{sides_label}: **{result.dice_rolls[0]}**"
        if result.flat_modifier or result.sheet_modifier:
            mods = []
            if result.flat_modifier:
                mods.append(format_modifier(result.flat_modifier))
            if result.sheet_modifier:
                mods.append(format_modifier(result.sheet_modifier))
            detail += f" ({' + '.join(mods)})"
    else:
        detail += f" · {dice_part}"
        if result.flat_modifier or result.sheet_modifier:
            mods = []
            if result.flat_modifier:
                mods.append(format_modifier(result.flat_modifier))
            if result.sheet_modifier:
                mods.append(format_modifier(result.sheet_modifier))
            detail += f" ({' + '.join(mods)})"

    if _effective_d20(result) == 20:
        detail += " · 🌟 **Natural 20!**"
    elif _effective_d20(result) == 1:
        detail += " · 💀 **Natural 1!**"

    lines.append(detail)
    return "\n".join(lines)
