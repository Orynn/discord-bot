import re
from typing import Any

_TAG = re.compile(r"\{@([^}]+)\}")
_DAMAGE = re.compile(r"\{@damage\s+([^}|]+)")

_SPELL_SCHOOLS = {
    "A": "Abjuration",
    "C": "Conjuration",
    "D": "Divination",
    "E": "Enchantment",
    "I": "Illusion",
    "N": "Necromancy",
    "T": "Transmutation",
    "V": "Evocation",
}

_DAMAGE_TYPES = {
    "B": "Bludgeoning",
    "P": "Piercing",
    "S": "Slashing",
    "A": "Acid",
    "C": "Cold",
    "F": "Fire",
    "Fo": "Force",
    "L": "Lightning",
    "N": "Necrotic",
    "O": "Poison",
    "Ps": "Psychic",
    "R": "Radiant",
    "T": "Thunder",
}

_DAMAGE_TYPE_EMOJI = {
    "Bludgeoning": "🔨",
    "Piercing": "🎯",
    "Slashing": "🗡️",
    "Acid": "🧪",
    "Cold": "❄️",
    "Fire": "🔥",
    "Force": "💫",
    "Lightning": "⚡",
    "Necrotic": "💀",
    "Poison": "☠️",
    "Psychic": "🧠",
    "Radiant": "☀️",
    "Thunder": "🌩️",
}


def spell_school(code: str | None) -> str:
    if not code:
        return "—"
    return _SPELL_SCHOOLS.get(code, code)


def damage_type(code: str | None) -> str:
    if not code:
        return "—"
    return format_damage_type_label(_DAMAGE_TYPES.get(code, code))


def format_damage_type_label(name: str) -> str:
    if not name or name == "—":
        return "—"
    normalized = name.strip().title()
    emoji = _DAMAGE_TYPE_EMOJI.get(normalized)
    if not emoji:
        return name
    prefix = f"{emoji} "
    if name.startswith(prefix):
        return name
    return f"{prefix}{normalized}"


def emojify_damage_types(text: str) -> str:
    if not text or text == "—":
        return text
    for name in sorted(_DAMAGE_TYPE_EMOJI, key=len, reverse=True):
        emoji = _DAMAGE_TYPE_EMOJI[name]
        marked = f"{emoji} {name} damage"
        text = re.sub(
            rf"(?:{re.escape(emoji)} )?{re.escape(name)}\s+damage\b",
            marked,
            text,
            flags=re.IGNORECASE,
        )
    return text


def spell_damage_type_label(spell: dict[str, Any] | None) -> str | None:
    if not spell:
        return None
    for key in ("damageInflict", "damage_types"):
        types = spell.get(key) or []
        if types:
            return format_damage_type_label(str(types[0]).replace("_", " ").title())
    return None


_ABILITY_NAMES = {
    "str": "Strength",
    "dex": "Dexterity",
    "con": "Constitution",
    "int": "Intelligence",
    "wis": "Wisdom",
    "cha": "Charisma",
}

_NAMED_TAGS = {
    "variantrule",
    "condition",
    "spell",
    "action",
    "skill",
    "item",
    "filter",
    "class",
    "classfeature",
    "itemmastery",
    "deity",
    "race",
    "feat",
    "reward",
    "language",
    "sense",
}


def _split_pipe(text: str) -> list[str]:
    return [segment.strip() for segment in text.split("|") if segment.strip()]


def _named_tag_display(rest: str) -> str:
    parts = _split_pipe(rest)
    if len(parts) >= 3:
        return parts[2]
    if parts:
        return parts[0]
    return ""


def _format_attack_tag(rest: str, *, is_roll: bool) -> str:
    tag_groups = [group.strip() for group in rest.split(",") if group.strip()]
    rendered: list[str] = []
    for group in tag_groups:
        tags = group.lower()
        attack_type = (
            "Melee "
            if "m" in tags
            else "Ranged "
            if "r" in tags
            else "Magical "
            if "g" in tags
            else "Area "
            if "a" in tags
            else ""
        )
        method = (
            "Weapon "
            if "w" in tags
            else "Spell "
            if "s" in tags
            else "Power "
            if "p" in tags
            else ""
        )
        rendered.append(f"{attack_type}{method}".strip())
    label = " or ".join(part for part in rendered if part) or "Attack"
    suffix = " Roll" if is_roll else ""
    return f"{label} Attack{suffix}:"


def _replace_tag(match: re.Match[str]) -> str:
    inner = match.group(1).strip()
    tag, _, rest = inner.partition(" ")
    tag_l = tag.lower()

    if tag_l == "h":
        return "Hit: "
    if tag_l == "m":
        return "Miss: "
    if tag_l == "hom":
        return "Hit or Miss: "
    if tag_l in {"atk", "atkr"}:
        return _format_attack_tag(rest, is_roll=tag_l == "atkr")
    if tag_l == "hit":
        bonus = rest.split("|", 1)[0].strip()
        if bonus and not bonus.startswith(("+", "-")):
            return f"+{bonus}"
        return bonus or "+0"
    if tag_l == "dc":
        value = rest.split("|", 1)[0].strip()
        return f"DC {value}" if value else "DC"
    if tag_l == "damage":
        return rest.split("|", 1)[0].strip() if rest else inner
    if tag_l == "dice":
        return rest.split("|", 1)[0].strip() if rest else inner
    if tag_l == "actsave":
        ability = rest.split("|", 1)[0].strip().lower()
        full = _ABILITY_NAMES.get(ability, ability.title())
        return f"{full} Saving Throw:"
    if tag_l == "actsavesuccess":
        return "Success:"
    if tag_l == "actsavefail":
        ordinal = rest.split("|", 1)[0].strip()
        return f"{ordinal} Failure:" if ordinal else "Failure:"
    if tag_l == "actsavefailby":
        amount = rest.split("|", 1)[0].strip()
        return f"Failure by {amount} or More:" if amount else "Failure by 5 or More:"
    if tag_l == "actsavesuccessorfail":
        return "Failure or Success:"
    if tag_l == "acttrigger":
        return "Trigger:"
    if tag_l == "actresponse":
        return "Response:" if "d" not in rest.lower() else "Response—"
    if tag_l == "b":
        return f"**{rest.split('|', 1)[0].strip()}**"
    if tag_l in _NAMED_TAGS:
        return _named_tag_display(rest)

    if "|" in rest:
        return rest.split("|", 1)[0].strip()
    return rest or tag


def clean_tags(text: str) -> str:
    text = _TAG.sub(_replace_tag, text)
    text = text.replace("{@i ", "*").replace("{@i", "*")
    text = re.sub(r"\{@(?:scaledice|filter|book|note|homebrew)[^}]*\}", "", text)
    text = re.sub(r"([A-Za-z]):(\d)", r"\1: \2", text)
    text = re.sub(r"  +", " ", text)
    return emojify_damage_types(text)


def render_entries(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return clean_tags(value).strip()
    if isinstance(value, list):
        parts = [render_entries(entry) for entry in value]
        return "\n\n".join(part for part in parts if part)
    if isinstance(value, dict):
        entry_type = value.get("type")
        if entry_type == "list":
            items = value.get("items") or []
            style = value.get("style")
            if style == "list-hang-notitle":
                return "\n".join(f"• {render_entries(item)}" for item in items if render_entries(item))
            return "\n".join(f"• {render_entries(item)}" for item in items if render_entries(item))
        if entry_type == "table":
            return ""
        name = value.get("name") or ""
        body = render_entries(value.get("entries") or value.get("entry") or value.get("items"))
        if name and body:
            return f"**{clean_tags(name)}.** {body}"
        if name:
            return f"**{clean_tags(name)}.**"
        return body
    return str(value).strip()


def spell_level_int(level: Any) -> int:
    if level in (None, "", 0, "0", "Cantrip", "cantrip"):
        return 0
    if isinstance(level, int):
        return level
    text = str(level).strip()
    if text.isdigit():
        return int(text)
    match = re.match(r"(\d+)", text)
    return int(match.group(1)) if match else 0


def format_spell_level(level: Any) -> str:
    if level in (0, "0", "Cantrip"):
        return "Cantrip"
    if isinstance(level, int):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(level % 10 if level % 100 not in (11, 12, 13) else 0, "th")
        return f"{level}{suffix}"
    return str(level)


def format_time(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        labels = {"action": "1 action", "bonus action": "1 bonus action", "reaction": "1 reaction"}
        return labels.get(value.strip().lower(), value)
    if isinstance(value, list) and value:
        return format_time(value[0])
    if isinstance(value, dict):
        number = value.get("number", 1)
        unit = value.get("unit", "")
        if unit == "action":
            return "1 action" if number == 1 else f"{number} actions"
        if unit == "bonus action":
            return "1 bonus action" if number == 1 else f"{number} bonus actions"
        if unit == "reaction":
            return "1 reaction"
        if unit == "minute":
            return f"{number} minute" if number == 1 else f"{number} minutes"
        if unit == "hour":
            return f"{number} hour" if number == 1 else f"{number} hours"
        return f"{number} {unit}".strip()
    return str(value)


def format_range(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        distance = value.get("distance") or {}
        amount = distance.get("amount")
        unit = distance.get("type") or "feet"
        range_type = value.get("type")
        if range_type == "point" and amount is not None:
            return f"{amount} {unit}"
        if range_type == "self":
            return "Self"
        if range_type == "touch":
            return "Touch"
        if range_type == "sight":
            return "Sight"
        if range_type == "unlimited":
            return "Unlimited"
        if amount is not None:
            return f"{amount} {unit}"
    return "—"


def format_duration(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value:
        return format_duration(value[0])
    if isinstance(value, dict):
        if value.get("type") == "instant":
            return "Instantaneous"
        amount = value.get("amount")
        unit = value.get("unit") or value.get("type")
        if amount and unit:
            if unit == "minute":
                return f"{amount} minute" if amount == 1 else f"{amount} minutes"
            if unit == "hour":
                return f"{amount} hour" if amount == 1 else f"{amount} hours"
            if unit == "round":
                return f"{amount} round" if amount == 1 else f"{amount} rounds"
            return f"{amount} {unit}"
        if unit == "permanent":
            return "Permanent"
        if unit:
            return str(unit).title()
    return "—"


def format_components(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        parts: list[str] = []
        if value.get("v"):
            parts.append("V")
        if value.get("s"):
            parts.append("S")
        if value.get("m"):
            parts.append("M")
        return ", ".join(parts) if parts else "—"
    return "—"


def format_cost(value: int | None) -> str:
    if value in (None, 0):
        return "—"
    return f"{value / 100:.2f}".rstrip("0").rstrip(".") + " gp"


_WEIGHT_TEXT = re.compile(
    r"^[\s—\-]*(\d+(?:[.,]\d+)?)\s*(?:lb|lbs|pounds?)?\.?\s*$",
    re.IGNORECASE,
)

# French PHB: 1 lb = 0.5 kg, so STR × 15 lb = STR × 7.5 kg.
KG_PER_LB = 0.5


def lb_to_kg(pounds: float | int) -> float:
    return float(pounds) * KG_PER_LB


def kg_to_lb(kilos: float | int) -> float:
    return float(kilos) / KG_PER_LB


def format_weight_from_lb(pounds: float | int) -> str:
    kg = lb_to_kg(pounds)
    if abs(kg - round(kg)) < 1e-9:
        return f"{int(round(kg))} kg"
    text = f"{round(kg, 2):.2f}".rstrip("0").rstrip(".")
    return f"{text} kg"


def parse_weight_lb(value: Any) -> float | None:
    if value in (None, "", "—", "-", False):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        return float(value)
    if isinstance(value, str):
        match = _WEIGHT_TEXT.match(value.strip())
        if not match:
            return None
        return float(match.group(1).replace(",", "."))
    if isinstance(value, dict):
        return parse_weight_lb(
            value.get("number") or value.get("lb") or value.get("weight")
        )
    return None


def format_weight(value: Any) -> str:
    parsed = value if isinstance(value, (int, float)) else parse_weight_lb(value)
    if parsed in (None, "") or parsed == 0:
        return "—"
    return format_weight_from_lb(parsed)


def slugify(name: str) -> str:
    cleaned = name.lower().replace("'", "").replace("’", "")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")
