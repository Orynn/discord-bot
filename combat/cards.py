import re
from dataclasses import asdict, dataclass, fields

HAND_SIZE = 5
DRAW_PER_TURN = 1
MAX_LOG_LINES = 8

WEAPON_CARD_ID = "srd:weapon"
DODGE_CARD_ID = "srd:dodge"

DEFAULT_SPELL_RANGE_SQUARES = 24
RANGE_NUMBER = re.compile(r"(\d+)")
DAMAGE_ROLL_PATTERN = re.compile(
    r"^(?:(\d+)d(\d+))?(?:\s*\+\s*(\d+))?$",
    re.IGNORECASE,
)

SPELLCASTING_ABILITY: dict[str, str] = {
    "artificer": "int",
    "bard": "cha",
    "cleric": "wis",
    "druid": "wis",
    "paladin": "cha",
    "ranger": "wis",
    "sorcerer": "cha",
    "warlock": "cha",
    "wizard": "int",
}

SCHOOL_EMOJI: dict[str, str] = {
    "abjuration": "🛡️",
    "conjuration": "✨",
    "divination": "👁️",
    "enchantment": "💫",
    "evocation": "🔥",
    "illusion": "🎭",
    "necromancy": "💀",
    "transmutation": "⚗️",
}


@dataclass(frozen=True)
class CardSnapshot:
    card_id: str
    label: str
    emoji: str
    description: str
    needs_target: bool
    target_allies_only: bool = False
    target_enemies_only: bool = False
    card_type: str = "action"
    dice_count: int = 0
    dice_sides: int = 0
    flat_modifier: int = 0
    is_healing: bool = False
    spell_level: int = 0
    spell_slug: str | None = None
    uses_proficiency: bool = False
    ability: str | None = None
    damage_type_label: str | None = None
    buff: str | None = None
    save_ability: str | None = None
    save_half: bool = False
    inflict_condition: str | None = None
    range_squares: int | None = None
    aoe_radius: int | None = None
    concentration: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CardSnapshot":
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in allowed})


def parse_damage_roll(notation: str | None) -> tuple[int, int, int]:
    if not notation:
        return 0, 0, 0
    cleaned = notation.strip().lower().replace(" ", "")
    match = DAMAGE_ROLL_PATTERN.match(cleaned)
    if not match:
        return 0, 0, 0
    count = int(match.group(1) or 0)
    sides = int(match.group(2) or 0)
    flat = int(match.group(3) or 0)
    return count, sides, flat


def spell_card_id(slug: str) -> str:
    return f"spell:{slug}"


def homebrew_card_id(name: str) -> str:
    return f"homebrew:{name.strip().lower().replace(' ', '-')}"


def card_label(card: CardSnapshot) -> str:
    return f"{card.emoji} {card.label}"


def card_description(card: CardSnapshot) -> str:
    return f"{card.emoji} **{card.label}** — {card.description}"


def lookup_card(catalog: dict[str, CardSnapshot], card_id: str) -> CardSnapshot | None:
    return catalog.get(card_id)


def is_spellbook_card(card: CardSnapshot) -> bool:
    return card.card_type in {"spell", "homebrew"}


def parse_range_squares(text: str | None) -> int | None:
    if not text:
        return None
    raw = str(text).strip().lower()
    if raw in {"—", "-", "n/a", ""}:
        return None
    if raw == "self" or raw.startswith("self"):
        return 0
    if raw in {"melee", "touch"} or raw.startswith("melee") or raw.startswith("touch"):
        return 1
    if raw in {"sight", "unlimited", "special"}:
        return None
    if "mile" in raw:
        return None
    match = RANGE_NUMBER.search(raw)
    if match is None:
        return None
    return max(1, int(match.group(1)) // 5)


def card_requires_target(card: CardSnapshot) -> bool:
    return card.needs_target or is_spellbook_card(card)


def resolve_card_id(query: str, catalog: dict[str, CardSnapshot]) -> str | None:
    normalized = query.strip().lower().replace(" ", "-")
    aliases = {
        "weapon": WEAPON_CARD_ID,
        "attack": WEAPON_CARD_ID,
        "strike": WEAPON_CARD_ID,
        "dodge": DODGE_CARD_ID,
    }
    if normalized in aliases and aliases[normalized] in catalog:
        return aliases[normalized]
    if normalized in catalog:
        return normalized
    for card_id, card in catalog.items():
        label_key = card.label.lower().replace(" ", "-")
        if normalized == label_key or normalized in label_key:
            return card_id
        if card.spell_slug and normalized in card.spell_slug:
            return card_id
    return None


AUTO_HIT_SLUGS = frozenset({"magic-missile"})


def card_makes_attack_roll(card: CardSnapshot) -> bool:
    if (
        card.save_ability
        or card.is_healing
        or card.dice_count <= 0
        or card.card_type == "dodge"
    ):
        return False
    slug = (card.spell_slug or "").lower()
    if slug in AUTO_HIT_SLUGS:
        return False
    return True


def normalize_save_ability(value: str | None) -> str | None:
    if not value:
        return None
    return _SAVE_ABILITIES.get(value.strip().lower())


def extract_damage_notation(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        tagged = _DAMAGE_TAG.search(text)
        if tagged:
            return tagged.group(1).strip()
        plain = _DAMAGE_TEXT.search(text)
        if plain:
            return plain.group(1).replace(" ", "")
    return None


def spell_save_ability(spell: dict) -> str | None:
    raw = (
        spell.get("savingThrow")
        or spell.get("saving_throw")
        or spell.get("save_ability")
    )
    if isinstance(raw, str):
        found = normalize_save_ability(raw)
        if found:
            return found
    if isinstance(raw, list):
        for item in raw:
            found = normalize_save_ability(str(item))
            if found:
                return found
    desc = str(spell.get("desc") or "")
    match = _SAVE_IN_TEXT.search(desc)
    if match:
        return normalize_save_ability(match.group(1))
    return None


def spell_save_half(spell: dict) -> bool:
    if spell.get("save_half"):
        return True
    desc = str(spell.get("desc") or "")
    return bool(_HALF_ON_SAVE.search(desc))


def spell_damage_roll(spell: dict) -> str | None:
    explicit = spell.get("damage_roll")
    if explicit:
        return str(explicit)
    types = spell.get("damage_types") or spell.get("damageInflict")
    has_save = bool(spell.get("savingThrow") or spell.get("saving_throw"))
    if (
        not types
        and not has_save
        and not is_healing_spell(
            damage_types=list(types or []), desc=str(spell.get("desc") or "")
        )
    ):
        return None
    entries = spell.get("entries")
    entry_text = ""
    if isinstance(entries, list):
        entry_text = " ".join(part for part in entries if isinstance(part, str))
    elif isinstance(entries, str):
        entry_text = entries
    return extract_damage_notation(entry_text, str(spell.get("desc") or ""))


BUFF_BY_SLUG: dict[str, str] = {
    "shield": "shield",
    "mage-armor": "mage-armor",
    "bless": "bless",
}

CONCENTRATION_SLUGS = frozenset(
    {
        "bless",
        "hex",
        "hunter-s-mark",
        "hold-person",
        "hold-monster",
        "spirit-guardians",
        "moonbeam",
        "faerie-fire",
        "web",
        "hypnotic-pattern",
        "cloudkill",
        "fly",
        "haste",
        "slow",
        "banishment",
        "greater-invisibility",
    }
)

AOE_RADIUS_BY_SLUG: dict[str, int] = {
    "fireball": 4,
    "shatter": 2,
    "thunderwave": 3,
    "burning-hands": 3,
    "ice-storm": 4,
    "flame-strike": 2,
    "spirit-guardians": 3,
    "moonbeam": 1,
    "cloudkill": 4,
    "hypnotic-pattern": 6,
    "sleep": 4,
}

_RADIUS_FEET = re.compile(
    r"(\d+)[-\s]*foot[-\s]*radius|rayon de\s*(\d+)",
    re.IGNORECASE,
)

_SAVE_ABILITIES: dict[str, str] = {
    "str": "str",
    "strength": "str",
    "dex": "dex",
    "dexterity": "dex",
    "con": "con",
    "constitution": "con",
    "int": "int",
    "intelligence": "int",
    "wis": "wis",
    "wisdom": "wis",
    "cha": "cha",
    "charisma": "cha",
}

_DAMAGE_TAG = re.compile(r"\{@damage\s+([^}|]+)", re.IGNORECASE)
_DAMAGE_TEXT = re.compile(r"(\d+d\d+(?:\s*\+\s*\d+)?)", re.IGNORECASE)
_SAVE_IN_TEXT = re.compile(
    r"\b(strength|dexterity|constitution|intelligence|wisdom|charisma|str|dex|con|int|wis|cha)"
    r"\s+saving throw",
    re.IGNORECASE,
)
_HALF_ON_SAVE = re.compile(
    r"half as much|half damage|demi[- ]d[eé]g[aâ]ts",
    re.IGNORECASE,
)


def card_buff(card: CardSnapshot) -> str | None:
    if card.buff:
        return card.buff
    if card.card_type == "dodge":
        return "dodge"
    slug = (card.spell_slug or "").lower()
    return BUFF_BY_SLUG.get(slug)


def is_healing_spell(*, damage_types: list[str] | None, desc: str) -> bool:
    if damage_types:
        return False
    lowered = desc.lower()
    return any(
        word in lowered for word in ("hit point", "regain", "healing", "restore")
    )


def parse_aoe_radius(spell: dict) -> int | None:
    slug = str(spell.get("slug") or "").lower()
    if slug in AOE_RADIUS_BY_SLUG:
        return AOE_RADIUS_BY_SLUG[slug]
    texts = [str(spell.get("range") or ""), str(spell.get("desc") or "")]
    entries = spell.get("entries")
    if isinstance(entries, list):
        texts.extend(str(part) for part in entries if isinstance(part, str))
    elif isinstance(entries, str):
        texts.append(entries)
    for text in texts:
        match = _RADIUS_FEET.search(text)
        if match:
            feet = int(match.group(1) or match.group(2))
            return max(1, feet // 5)
    return None


def spell_requires_concentration(spell: dict) -> bool:
    slug = str(spell.get("slug") or "").lower()
    if slug in CONCENTRATION_SLUGS:
        return True
    raw = spell.get("duration")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("concentration"):
                return True
            if "concentration" in str(item).lower():
                return True
    return "concentration" in str(raw or "").lower()


def spellcasting_ability(char_class: str) -> str | None:
    if not char_class:
        return None
    key = char_class.lower().strip().split()[0]
    return SPELLCASTING_ABILITY.get(key)


def weapon_attack_ability(char_class: str, abilities: dict[str, int]) -> str:
    key = char_class.lower().strip().split()[0] if char_class else ""
    if key in {"rogue", "ranger", "monk"}:
        return "dex" if abilities.get("dex", 10) >= abilities.get("str", 10) else "str"
    return "str"
