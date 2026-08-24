import math
import re
from typing import Any

from campaign.clock import MINUTES_PER_DAY, CampaignTime, absolute_day
from sheets.data import CharacterSheet, ability_modifier
from sheets.equipment import Equipment, InventoryItem

FED_NONE = ""
FED_FULL = "full"
FED_HALF = "half"

_EXHAUSTION = re.compile(r"^exhaust(?:ion)?(?:\s+|:)(\d+)$", re.IGNORECASE)
_RATION_TOKENS = ("ration", "vivres", "provisions", "food")


def starvation_limit(con_score: int) -> int:
    return max(1, 3 + ability_modifier(int(con_score)))


def sheet_starvation_limit(sheet: CharacterSheet) -> int:
    return starvation_limit(sheet.abilities.get("con", 10) or 10)


def format_hunger_days(days: float) -> str:
    value = float(days)
    if value <= 0:
        return "0 days"
    if value == 0.5:
        return "half a day"
    if value == int(value):
        count = int(value)
        return "1 day" if count == 1 else f"{count} days"
    return f"{value:g} days"


def exhaustion_level(sheet: CharacterSheet) -> int:
    level = 0
    for condition in sheet.conditions:
        match = _EXHAUSTION.match(str(condition).strip())
        if match:
            level = max(level, int(match.group(1)))
    return level


def set_exhaustion_level(sheet: CharacterSheet, level: int) -> None:
    sheet.conditions = [
        condition
        for condition in sheet.conditions
        if not _EXHAUSTION.match(str(condition).strip())
    ]
    if level >= 1:
        sheet.conditions.append(f"exhaustion {min(int(level), 6)}")


def find_ration_item(equipment: Equipment) -> InventoryItem | None:
    matches: list[InventoryItem] = []
    for item in equipment.items:
        blob = f"{item.name} {item.slug}".lower()
        if any(token in blob for token in _RATION_TOKENS):
            matches.append(item)
    if not matches:
        return None
    return sorted(matches, key=lambda item: item.quantity, reverse=True)[0]


def consume_ration(sheet: CharacterSheet) -> InventoryItem | None:
    item = find_ration_item(sheet.equipment)
    if item is None:
        return None
    return sheet.equipment.remove_item(item.name, quantity=1)


def meal_clock(sheet: CharacterSheet) -> CampaignTime | None:
    if sheet.hunger_meal_year is None or sheet.hunger_meal_day is None:
        return None
    return CampaignTime(
        year=int(sheet.hunger_meal_year),
        day_index=int(sheet.hunger_meal_day),
        minute=0,
    )


def stamp_meal(sheet: CharacterSheet, clock: CampaignTime, kind: str) -> None:
    sheet.hunger_meal_year = int(clock.year)
    sheet.hunger_meal_day = int(clock.day_index)
    sheet.hunger_meal_kind = kind


def hunger_days_from_clock(sheet: CharacterSheet, clock: CampaignTime) -> float:
    meal = meal_clock(sheet)
    if meal is None:
        return max(0.0, float(sheet.hunger_days))
    delta = absolute_day(clock) - absolute_day(meal)
    if delta < 0:
        return 0.0
    kind = sheet.hunger_meal_kind or FED_FULL
    if delta == 0:
        return 0.5 if kind == FED_HALF else 0.0
    missed = float(delta - 1)
    if kind == FED_HALF:
        return missed + 0.5
    return missed


def _fed_today_from_clock(sheet: CharacterSheet, clock: CampaignTime) -> str:
    meal = meal_clock(sheet)
    if meal is None:
        return sheet.fed_today
    if absolute_day(clock) != absolute_day(meal):
        return FED_NONE
    return sheet.hunger_meal_kind or FED_FULL


def hunger_state(sheet: CharacterSheet) -> str:
    limit = sheet_starvation_limit(sheet)
    days = float(sheet.hunger_days)
    if sheet.fed_today == FED_FULL:
        return "fed"
    if days <= 0 and sheet.fed_today != FED_HALF:
        return "fed"
    if days > limit:
        return "starving"
    if sheet.fed_today == FED_HALF or days > 0:
        return "hungry"
    return "fed"


def format_hunger_line(sheet: CharacterSheet) -> str:
    limit = sheet_starvation_limit(sheet)
    days = float(sheet.hunger_days)
    bits = [f"{format_hunger_days(days)} without food · limit {limit}"]
    if sheet.fed_today == FED_FULL:
        bits.append("ate today")
    elif sheet.fed_today == FED_HALF:
        bits.append("half rations today")
    if days > limit:
        level = exhaustion_level(sheet)
        if level:
            bits.append(f"exhaustion {level}")
        else:
            bits.append("starving")
    return " · ".join(bits)


def eat_full(sheet: CharacterSheet, clock: CampaignTime | None = None) -> None:
    sheet.hunger_days = 0.0
    sheet.fed_today = FED_FULL
    if clock is not None:
        stamp_meal(sheet, clock, FED_FULL)


def eat_half(sheet: CharacterSheet, clock: CampaignTime | None = None) -> None:
    if sheet.fed_today == FED_FULL:
        return
    sheet.fed_today = FED_HALF
    if clock is not None:
        stamp_meal(sheet, clock, FED_HALF)
    if float(sheet.hunger_days) <= 0:
        sheet.hunger_days = 0.0


def set_hunger_days(
    sheet: CharacterSheet, days: float, clock: CampaignTime | None = None
) -> None:
    sheet.hunger_days = max(0.0, float(days))
    if sheet.hunger_days <= 0:
        sheet.fed_today = FED_FULL
        if clock is not None:
            stamp_meal(sheet, clock, FED_FULL)
        return
    sheet.fed_today = FED_NONE
    if clock is not None:
        back = int(math.floor(sheet.hunger_days)) + 1
        past = clock.advance(-back * MINUTES_PER_DAY)
        kind = FED_HALF if sheet.hunger_days % 1 == 0.5 else FED_FULL
        stamp_meal(sheet, past, kind)


def _apply_starvation_crossings(
    sheet: CharacterSheet, before: float, after: float
) -> list[str]:
    notices: list[str] = []
    limit = sheet_starvation_limit(sheet)
    threshold = math.floor(before) + 1
    while threshold <= after:
        if threshold > limit:
            level = min(6, exhaustion_level(sheet) + 1)
            set_exhaustion_level(sheet, level)
            if level >= 6:
                notices.append(f"starvation → exhaustion {level} (death)")
                break
            notices.append(f"starvation → exhaustion {level}")
        threshold += 1
    return notices


def advance_hunger(sheet: CharacterSheet, calendar_days: int) -> list[str]:
    days = int(calendar_days)
    if days <= 0:
        return []
    notices: list[str] = []
    for index in range(days):
        before = float(sheet.hunger_days)
        fed = sheet.fed_today if index == 0 else FED_NONE
        if fed == FED_FULL:
            sheet.hunger_days = 0.0
        elif fed == FED_HALF:
            sheet.hunger_days = before + 0.5
        else:
            sheet.hunger_days = before + 1.0
        sheet.fed_today = FED_NONE
        notices.extend(
            _apply_starvation_crossings(sheet, before, float(sheet.hunger_days))
        )
    return notices


def skip_hunger_day(sheet: CharacterSheet) -> list[str]:
    sheet.fed_today = FED_NONE
    return advance_hunger(sheet, 1)


def parse_hunger_days(text: str) -> float:
    cleaned = text.strip().lower().replace(",", ".")
    cleaned = (
        cleaned.replace(" days", "")
        .replace(" day", "")
        .replace(" jours", "")
        .replace(" jour", "")
    )
    if cleaned in {"0", "fed", "full", "rassasie", "rassasié"}:
        return 0.0
    if cleaned in {"half", "demi", "0.5", "1/2"}:
        return 0.5
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError(
            "Hunger must be a number of days, e.g. `0`, `2`, `2.5`."
        ) from exc
    if value < 0 or value > 30:
        raise ValueError("Hunger days must be between 0 and 30.")
    return value


def hunger_embed_color(sheet: CharacterSheet) -> int:
    state = hunger_state(sheet)
    if state == "starving":
        return 0xC0392B
    if state == "hungry":
        return 0xE67E22
    return 0x27AE60


def _seed_meal_from_clock(sheet: CharacterSheet, clock: CampaignTime) -> None:
    if sheet.hunger_meal_year is not None and sheet.hunger_meal_day is not None:
        return
    if sheet.fed_today == FED_FULL:
        stamp_meal(sheet, clock, FED_FULL)
        return
    if sheet.fed_today == FED_HALF:
        stamp_meal(sheet, clock, FED_HALF)
        return
    days = float(sheet.hunger_days)
    if days <= 0:
        stamp_meal(sheet, clock.advance(-MINUTES_PER_DAY), FED_FULL)
        return
    back = int(math.floor(days)) + 1
    kind = FED_HALF if days % 1 == 0.5 else FED_FULL
    stamp_meal(sheet, clock.advance(-back * MINUTES_PER_DAY), kind)


def sync_hunger_to_clock(sheet: CharacterSheet, clock: CampaignTime) -> list[str]:
    _seed_meal_from_clock(sheet, clock)
    before = float(sheet.hunger_days)
    after = hunger_days_from_clock(sheet, clock)
    sheet.fed_today = _fed_today_from_clock(sheet, clock)
    sheet.hunger_days = after
    return _apply_starvation_crossings(sheet, before, after)


def tick_hunger_for_clock(
    *,
    guild_id: int,
    user_id: int,
    previous: Any,
    current: Any,
) -> list[str]:
    from campaign.clock import calendar_days_between
    from sheets.storage import get_sheet, save_sheet

    sheet = get_sheet(user_id=user_id, guild_id=guild_id)
    if sheet is None:
        return []
    days = calendar_days_between(previous, current)
    _seed_meal_from_clock(sheet, previous)
    notices = sync_hunger_to_clock(sheet, current)
    save_sheet(user_id=user_id, guild_id=guild_id, sheet=sheet)
    name = sheet.name
    lines = [f"**{name}**: {notice}" for notice in notices]
    if days > 0:
        lines.insert(0, f"**{name}** — {format_hunger_line(sheet)}")
    return lines
