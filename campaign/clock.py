from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MINUTES_PER_HOUR = 60
HOURS_PER_DAY = 24
MINUTES_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR
DEFAULT_YEAR = 1492
DEFAULT_MINUTE = 8 * MINUTES_PER_HOUR

TENDAY_NAMES = (
    "1st-day",
    "2nd-day",
    "3rd-day",
    "4th-day",
    "5th-day",
    "6th-day",
    "7th-day",
    "8th-day",
    "9th-day",
    "10th-day",
)


@dataclass(frozen=True)
class _Segment:
    name: str
    length: int
    festival: bool = False
    leap_only: bool = False


_SEGMENTS: tuple[_Segment, ...] = (
    _Segment("Hammer", 30),
    _Segment("Midwinter", 1, festival=True),
    _Segment("Alturiak", 30),
    _Segment("Ches", 30),
    _Segment("Tarsakh", 30),
    _Segment("Greengrass", 1, festival=True),
    _Segment("Mirtul", 30),
    _Segment("Kythorn", 30),
    _Segment("Flamerule", 30),
    _Segment("Midsummer", 1, festival=True),
    _Segment("Shieldmeet", 1, festival=True, leap_only=True),
    _Segment("Eleasis", 30),
    _Segment("Eleint", 30),
    _Segment("Highharvestide", 1, festival=True),
    _Segment("Marpenoth", 30),
    _Segment("Uktar", 30),
    _Segment("The Feast of the Moon", 1, festival=True),
    _Segment("Nightal", 30),
)

_MONTH_ALIASES: dict[str, str] = {
    "hammer": "Hammer",
    "marteau": "Hammer",
    "alturiak": "Alturiak",
    "ches": "Ches",
    "tarsakh": "Tarsakh",
    "mirtul": "Mirtul",
    "kythorn": "Kythorn",
    "flamerule": "Flamerule",
    "eleasis": "Eleasis",
    "eleint": "Eleint",
    "marpenoth": "Marpenoth",
    "uktar": "Uktar",
    "nightal": "Nightal",
}

_FESTIVAL_ALIASES: dict[str, str] = {
    "midwinter": "Midwinter",
    "greengrass": "Greengrass",
    "midsummer": "Midsummer",
    "shieldmeet": "Shieldmeet",
    "highharvestide": "Highharvestide",
    "high harvestide": "Highharvestide",
    "feast of the moon": "The Feast of the Moon",
    "the feast of the moon": "The Feast of the Moon",
    "fete de la lune": "The Feast of the Moon",
    "fête de la lune": "The Feast of the Moon",
}

_DURATION_TOKEN = re.compile(
    r"(\d+)\s*(weeks?|semaines?|w|days?|jours?|j|d|hours?|heures?|hrs?|h|minutes?|mins?|m)\b",
    re.IGNORECASE,
)
_COMPACT_HOUR_MINUTE = re.compile(r"^(\d+)\s*h\s*(\d{1,2})$", re.IGNORECASE)
_CLOCK_TIME = re.compile(
    r"(?:(\d{1,2})[:hH](\d{2})(?:\s*(am|pm))?|(\d{1,2})\s*(am|pm)|(\d{1,2})\s*h)\s*$",
    re.IGNORECASE,
)
_SKIP_ALIASES = {
    "dawn": 6,
    "aube": 6,
    "sunrise": 6,
    "noon": 12,
    "midi": 12,
    "dusk": 18,
    "crepuscule": 18,
    "crépuscule": 18,
    "sunset": 18,
    "midnight": 0,
    "minuit": 0,
    "night": 21,
    "nuit": 21,
}


@dataclass(frozen=True)
class CalendarDay:
    name: str
    festival: bool
    month: str | None
    day: int | None


@dataclass
class CampaignTime:
    year: int = DEFAULT_YEAR
    day_index: int = 0
    minute: int = DEFAULT_MINUTE

    def to_dict(self) -> dict[str, int]:
        return {"year": self.year, "day_index": self.day_index, "minute": self.minute}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CampaignTime":
        if not data:
            return cls()
        year = int(data.get("year", DEFAULT_YEAR))
        day_index = int(data.get("day_index", 0))
        minute = int(data.get("minute", DEFAULT_MINUTE))
        clock = cls(year=year, day_index=0, minute=0)
        return clock._normalized(day_index=day_index, minute=minute)

    def _normalized(self, *, day_index: int, minute: int) -> "CampaignTime":
        year = self.year
        total_minutes = day_index * MINUTES_PER_DAY + minute
        while total_minutes < 0:
            year -= 1
            total_minutes += year_length(year) * MINUTES_PER_DAY
        while True:
            year_minutes = year_length(year) * MINUTES_PER_DAY
            if total_minutes < year_minutes:
                break
            total_minutes -= year_minutes
            year += 1
        return CampaignTime(
            year=year,
            day_index=total_minutes // MINUTES_PER_DAY,
            minute=total_minutes % MINUTES_PER_DAY,
        )

    def advance(self, minutes: int) -> "CampaignTime":
        return self._normalized(day_index=self.day_index, minute=self.minute + int(minutes))

    def skip_to_hour(self, hour: int) -> "CampaignTime":
        target = max(0, min(23, hour)) * MINUTES_PER_HOUR
        if self.minute < target:
            return CampaignTime(year=self.year, day_index=self.day_index, minute=target)
        return self.advance(MINUTES_PER_DAY - self.minute + target)

    def calendar_day(self) -> CalendarDay:
        days = days_of_year(self.year)
        return days[min(self.day_index, len(days) - 1)]

    def tenday(self) -> str:
        return TENDAY_NAMES[absolute_day(self) % 10]

    def period(self) -> str:
        hour = self.minute // MINUTES_PER_HOUR
        if 5 <= hour < 8:
            return "dawn"
        if 8 <= hour < 12:
            return "morning"
        if 12 <= hour < 14:
            return "noon"
        if 14 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 20:
            return "dusk"
        return "night"

    def format_clock(self) -> str:
        return f"{self.minute // MINUTES_PER_HOUR:02d}:{self.minute % MINUTES_PER_HOUR:02d}"

    def format_date(self) -> str:
        day = self.calendar_day()
        if day.festival:
            return f"{day.name}, {self.year} DR"
        assert day.day is not None and day.month is not None
        return f"the {ordinal(day.day)} of {day.month}, {self.year} DR"

    def format_line(self) -> str:
        return f"{self.format_date()} · {self.format_clock()} · {self.period()}"

    def minutes_until_hour(self, hour: int) -> int:
        target = max(0, min(23, hour)) * MINUTES_PER_HOUR
        if self.minute < target:
            return target - self.minute
        return MINUTES_PER_DAY - self.minute + target


def calendar_days_between(previous: CampaignTime, current: CampaignTime) -> int:
    return max(0, absolute_day(current) - absolute_day(previous))


def is_leap(year: int) -> bool:
    return year % 4 == 0


def year_length(year: int) -> int:
    return 366 if is_leap(year) else 365


def days_of_year(year: int) -> list[CalendarDay]:
    days: list[CalendarDay] = []
    for segment in _SEGMENTS:
        if segment.leap_only and not is_leap(year):
            continue
        if segment.festival:
            days.append(CalendarDay(name=segment.name, festival=True, month=None, day=None))
            continue
        for day in range(1, segment.length + 1):
            days.append(CalendarDay(name=segment.name, festival=False, month=segment.name, day=day))
    return days


def absolute_day(clock: CampaignTime) -> int:
    total = clock.day_index
    if clock.year >= 1:
        for year in range(1, clock.year):
            total += year_length(year)
        return total
    for year in range(clock.year, 1):
        total -= year_length(year)
    return total


def ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def format_duration(minutes: int) -> str:
    remaining = abs(int(minutes))
    days, remaining = divmod(remaining, MINUTES_PER_DAY)
    hours, remaining = divmod(remaining, MINUTES_PER_HOUR)
    parts: list[str] = []
    if days:
        parts.append(f"{days} day" if days == 1 else f"{days} days")
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if remaining or not parts:
        parts.append(f"{remaining} minute" if remaining == 1 else f"{remaining} minutes")
    label = ", ".join(parts)
    if minutes < 0:
        return f"-{label}"
    return label


def parse_duration(text: str) -> int:
    cleaned = text.strip().lower()
    if not cleaned:
        raise ValueError("Missing duration. Examples: `2h`, `3d`, `1h 30m`, `8 hours`.")

    compact = _COMPACT_HOUR_MINUTE.match(cleaned)
    if compact:
        hours = int(compact.group(1))
        minutes = int(compact.group(2))
        if minutes >= 60:
            raise ValueError("Minutes must be between 0 and 59.")
        return hours * MINUTES_PER_HOUR + minutes

    rest_alias = {
        "short": MINUTES_PER_HOUR,
        "long": 8 * MINUTES_PER_HOUR,
        "short rest": MINUTES_PER_HOUR,
        "long rest": 8 * MINUTES_PER_HOUR,
    }
    if cleaned in rest_alias:
        return rest_alias[cleaned]

    total = 0
    for match in _DURATION_TOKEN.finditer(cleaned):
        amount = int(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith(("w", "semaine")):
            total += amount * 10 * MINUTES_PER_DAY
        elif unit.startswith(("d", "j", "day", "jour")):
            total += amount * MINUTES_PER_DAY
        elif unit.startswith(("h", "hour", "heure", "hr")):
            total += amount * MINUTES_PER_HOUR
        else:
            total += amount
    leftover = _DURATION_TOKEN.sub("", cleaned)
    leftover = re.sub(r"[\s,+]+", "", leftover)
    if total <= 0 or leftover:
        raise ValueError("Invalid duration. Examples: `2h`, `3d`, `1h 30m`, `8 hours`.")
    return total


def parse_skip_period(text: str) -> int | None:
    return _SKIP_ALIASES.get(text.strip().lower())


def _parse_clock_time(text: str) -> tuple[str, int]:
    match = _CLOCK_TIME.search(text.strip())
    if not match:
        return text.strip(), DEFAULT_MINUTE
    hour_raw = match.group(1) or match.group(4) or match.group(6)
    minute_raw = match.group(2) or "0"
    meridiem = (match.group(3) or match.group(5) or "").lower()
    hour = int(hour_raw)
    minute = int(minute_raw)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour == 24 and minute == 0:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("Time must be between 00:00 and 23:59.")
    remainder = text[: match.start()].strip(" ,-")
    return remainder, hour * MINUTES_PER_HOUR + minute


def parse_clock_set(text: str) -> CampaignTime:
    remainder, minute = _parse_clock_time(text)
    cleaned = re.sub(r"[,]+", " ", remainder)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError("Missing date. Example: `12 Hammer 1492 14:00`.")

    festival_key = cleaned.lower()
    year = DEFAULT_YEAR
    year_match = re.search(r"\b(\d{3,4})\b", cleaned)
    if year_match:
        year = int(year_match.group(1))
        festival_key = (cleaned[: year_match.start()] + cleaned[year_match.end() :]).strip()
        festival_key = re.sub(r"\bdr\b", "", festival_key, flags=re.IGNORECASE).strip()

    festival_name = _FESTIVAL_ALIASES.get(festival_key.lower())
    if festival_name:
        return _clock_for_named_day(year=year, name=festival_name, minute=minute)

    tokens = festival_key.split()
    day_number: int | None = None
    month_name: str | None = None
    leftover: list[str] = []
    for token in tokens:
        stripped = re.sub(r"(st|nd|rd|th)$", "", token, flags=re.IGNORECASE)
        alias = _MONTH_ALIASES.get(token.lower()) or _MONTH_ALIASES.get(stripped.lower())
        if alias:
            month_name = alias
            continue
        if stripped.isdigit() and day_number is None and 1 <= int(stripped) <= 30:
            day_number = int(stripped)
            continue
        leftover.append(token)
    leftover_ok = {"of", "the", "le", "du", "de", "la"}
    if leftover and not all(token.lower() in leftover_ok for token in leftover):
        raise ValueError("Could not read that date. Example: `12 Hammer 1492 14:00`.")
    if month_name is None or day_number is None:
        raise ValueError("Could not read that date. Example: `12 Hammer 1492 14:00`.")
    return _clock_for_month_day(year=year, month=month_name, day=day_number, minute=minute)


def _clock_for_named_day(*, year: int, name: str, minute: int) -> CampaignTime:
    days = days_of_year(year)
    for index, day in enumerate(days):
        if day.name.lower() == name.lower():
            return CampaignTime(year=year, day_index=index, minute=minute)
    raise ValueError(f"**{name}** does not fall in {year} DR.")


def _clock_for_month_day(*, year: int, month: str, day: int, minute: int) -> CampaignTime:
    days = days_of_year(year)
    for index, entry in enumerate(days):
        if entry.month == month and entry.day == day:
            return CampaignTime(year=year, day_index=index, minute=minute)
    raise ValueError(f"**{month}** has no day {day}.")
