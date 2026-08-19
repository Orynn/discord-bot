import re
from dataclasses import asdict, dataclass

HAND_SIZE = 5
DRAW_PER_TURN = 1
MAX_LOG_LINES = 8

WEAPON_CARD_ID = "srd:weapon"
DODGE_CARD_ID = "srd:dodge"

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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "CardSnapshot":
        return cls(**data)


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


def is_healing_spell(*, damage_types: list[str] | None, desc: str) -> bool:
    if damage_types:
        return False
    lowered = desc.lower()
    return any(word in lowered for word in ("hit point", "regain", "healing", "restore"))


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
