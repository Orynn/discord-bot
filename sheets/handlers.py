import re
from dataclasses import dataclass

from sheets.data import CharacterSheet

_HP_TOKEN = re.compile(r"^([+-])?(\d+)(?:/(\d+))?$")
HP_USAGE = "`hp -4` · `hp +6` · `hp 12` (valeur, pas un soin) · `hp 12/20`"


@dataclass(frozen=True)
class HpUpdate:
    previous: int
    current: int
    maximum: int
    delta: int | None


def apply_hp(sheet: CharacterSheet, current: int, maximum: int | None = None) -> None:
    if current < 0:
        raise ValueError("Current HP cannot be negative.")

    sheet.hp_current = current
    if maximum is not None:
        if maximum < 1:
            raise ValueError("Max HP must be at least 1.")
        sheet.hp_max = maximum
    elif sheet.hp_max == 0:
        sheet.hp_max = current

    if sheet.hp_current > sheet.hp_max:
        sheet.hp_current = sheet.hp_max
    if sheet.hp_current > 0:
        sheet.reset_death_saves()


def apply_hp_spec(sheet: CharacterSheet, spec: str) -> HpUpdate:
    tokens = spec.strip().split()
    if not tokens or len(tokens) > 2:
        raise ValueError(f"Missing HP value. Usage: {HP_USAGE}")

    match = _HP_TOKEN.fullmatch(tokens[0])
    if match is None:
        raise ValueError(f"Invalid HP value. Usage: {HP_USAGE}")

    sign, value_text, slash_max = match.groups()
    value = int(value_text)
    maximum = int(slash_max) if slash_max else None
    if len(tokens) == 2:
        if sign or slash_max or not tokens[1].isdigit():
            raise ValueError(f"Invalid HP value. Usage: {HP_USAGE}")
        maximum = int(tokens[1])

    previous = sheet.hp_current
    if sign:
        delta = value if sign == "+" else -value
        apply_hp(sheet, max(0, previous + delta), maximum)
        applied = sheet.hp_current - previous
        return HpUpdate(previous, sheet.hp_current, sheet.hp_max, applied)

    apply_hp(sheet, value, maximum)
    return HpUpdate(previous, sheet.hp_current, sheet.hp_max, None)


def format_hp_update(label: str, update: HpUpdate) -> str:
    if update.delta:
        return (
            f"{label}: HP **{update.previous} → {update.current}**/{update.maximum} "
            f"({update.delta:+d})."
        )
    if update.previous != update.current:
        return f"{label}: HP **{update.previous} → {update.current}**/{update.maximum}."
    return f"{label}: HP **{update.current}/{update.maximum}**."
