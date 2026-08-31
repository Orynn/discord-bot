import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from sheets.currency import Currency
from sheets.equipment import (
    CARRY_CAPACITY_PER_STR,
    Equipment,
    encumbered_speed,
    format_load_line,
)
from sheets.spell_slots import SpellSlots
from srd.spell_slugs import migrate_spell_slugs, normalize_stored_spell_slug

ABILITIES: tuple[str, ...] = ("str", "dex", "con", "int", "wis", "cha")

SKILL_ABILITIES: dict[str, str] = {
    "acrobatics": "dex",
    "animal_handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight_of_hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}

SKILL_ALIASES: dict[str, str] = {
    "acrobaties": "acrobatics",
    "acrobatie": "acrobatics",
    "dressage": "animal_handling",
    "dressage_d_animaux": "animal_handling",
    "dressage_animaux": "animal_handling",
    "arcanes": "arcana",
    "arcane": "arcana",
    "athletisme": "athletics",
    "tromperie": "deception",
    "histoire": "history",
    "intuition": "insight",
    "medecine": "medicine",
    "representation": "performance",
    "escamotage": "sleight_of_hand",
    "discretion": "stealth",
    "survie": "survival",
}


def fold_lookup_key(text: str) -> str:
    cleaned = text.lower().replace("-", " ").replace("'", " ").replace("’", " ").strip()
    stripped = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(ch)
    )
    return "_".join(stripped.split())


def lookup_skill(text: str) -> str | None:
    key = fold_lookup_key(text)
    if key in SKILL_ABILITIES:
        return key
    return SKILL_ALIASES.get(key)


SETTABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "species",
        "char_class",
        "subclass",
        "level",
        "background",
        "ac",
        "speed",
        "notes",
        *ABILITIES,
    }
)


def ability_modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    if level < 1:
        return 2
    return 2 + (level - 1) // 4


def format_modifier(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


HIT_DIE_SIDES: dict[str, int] = {
    "barbarian": 12,
    "fighter": 10,
    "paladin": 10,
    "ranger": 10,
    "artificer": 8,
    "bard": 8,
    "cleric": 8,
    "druid": 8,
    "monk": 8,
    "rogue": 8,
    "warlock": 8,
    "sorcerer": 6,
    "wizard": 6,
}


def hit_die_sides(char_class: str) -> int:
    if not char_class:
        return 8
    key = char_class.lower().strip().split()[0]
    return HIT_DIE_SIDES.get(key, 8)


@dataclass
class CharacterSheet:
    name: str
    species: str = ""
    char_class: str = ""
    subclass: str = ""
    level: int = 1
    background: str = ""
    abilities: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(ABILITIES, 10)
    )
    hp_max: int = 0
    hp_current: int = 0
    ac: int = 10
    speed: int = 30
    save_proficiencies: list[str] = field(default_factory=list)
    skill_proficiencies: list[str] = field(default_factory=list)
    skill_expertise: list[str] = field(default_factory=list)
    spells: list[str] = field(default_factory=list)
    homebrew_spells: list[str] = field(default_factory=list)
    spell_slots: SpellSlots = field(default_factory=SpellSlots)
    currency: Currency = field(default_factory=Currency)
    equipment: Equipment = field(default_factory=Equipment)
    conditions: list[str] = field(default_factory=list)
    inspired: bool = False
    death_save_successes: int = 0
    death_save_failures: int = 0
    hit_dice_remaining: int = 0
    hunger_days: float = 0.0
    fed_today: str = ""
    hunger_meal_year: int | None = None
    hunger_meal_day: int | None = None
    hunger_meal_kind: str = ""
    notes: str = ""
    image_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["spell_slots"] = self.spell_slots.to_dict()
        data["currency"] = self.currency.to_dict()
        data["equipment"] = self.equipment.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterSheet":
        abilities = dict.fromkeys(ABILITIES, 10)
        abilities.update(data.get("abilities", {}))
        spells, _ = migrate_spell_slugs(list(data.get("spells", [])))
        return cls(
            name=data["name"],
            species=data.get("species", ""),
            char_class=data.get("char_class", ""),
            subclass=data.get("subclass", ""),
            level=data.get("level", 1),
            background=data.get("background", ""),
            abilities=abilities,
            hp_max=data.get("hp_max", 0),
            hp_current=data.get("hp_current", 0),
            ac=data.get("ac", 10),
            speed=data.get("speed", 30),
            save_proficiencies=list(data.get("save_proficiencies", [])),
            skill_proficiencies=list(data.get("skill_proficiencies", [])),
            skill_expertise=list(data.get("skill_expertise", [])),
            spells=spells,
            homebrew_spells=list(data.get("homebrew_spells", [])),
            spell_slots=SpellSlots.from_dict(data.get("spell_slots")),
            currency=Currency.from_dict(data.get("currency")),
            equipment=Equipment.from_dict(data.get("equipment")),
            conditions=list(data.get("conditions", [])),
            inspired=bool(data.get("inspired", False)),
            death_save_successes=int(data.get("death_save_successes", 0)),
            death_save_failures=int(data.get("death_save_failures", 0)),
            hit_dice_remaining=int(
                data.get("hit_dice_remaining", data.get("level", 1))
            ),
            hunger_days=float(data.get("hunger_days", 0) or 0),
            fed_today=str(data.get("fed_today", "") or ""),
            hunger_meal_year=(
                int(data["hunger_meal_year"])
                if data.get("hunger_meal_year") is not None
                else None
            ),
            hunger_meal_day=(
                int(data["hunger_meal_day"])
                if data.get("hunger_meal_day") is not None
                else None
            ),
            hunger_meal_kind=str(data.get("hunger_meal_kind", "") or ""),
            notes=data.get("notes", ""),
            image_url=str(data.get("image_url", "") or ""),
        )

    def __post_init__(self) -> None:
        if self.hit_dice_remaining <= 0:
            self.hit_dice_remaining = self.level

    def get_prof_bonus(self) -> int:
        return proficiency_bonus(self.level)

    def carrying_capacity_lb(self) -> int:
        strength = self.abilities.get("str", 10)
        if strength is None:
            strength = 10
        return max(0, int(strength)) * CARRY_CAPACITY_PER_STR

    def carried_weight_lb(self) -> float:
        return self.equipment.carried_weight_lb(coin_lb=self.currency.weight_lb())

    def is_overloaded(self) -> bool:
        return self.carried_weight_lb() > self.carrying_capacity_lb()

    def effective_speed(self) -> int:
        return encumbered_speed(
            base_speed=int(self.speed or 0),
            carried_lb=self.carried_weight_lb(),
            capacity_lb=self.carrying_capacity_lb(),
        )

    def format_speed(self) -> str:
        current = self.effective_speed()
        base = int(self.speed or 0)
        if current < base:
            return f"**{current} ft.** (base {base})"
        return f"{base} ft."

    def format_load(self) -> str:
        coin_lb = self.currency.weight_lb()
        counted_coins = (
            coin_lb if self.equipment.coins_count_toward_load(coin_lb) else 0
        )
        return format_load_line(
            gear_lb=self.equipment.carried_weight_lb(coin_lb=0),
            coin_lb=counted_coins,
            capacity_lb=self.carrying_capacity_lb(),
            speed_ft=self.effective_speed(),
            base_speed=int(self.speed or 0),
        )

    def get_hit_die_sides(self) -> int:
        return hit_die_sides(self.char_class)

    def get_save_modifier(self, ability: str) -> int:
        mod = ability_modifier(self.abilities[ability])
        if ability in self.save_proficiencies:
            mod += self.get_prof_bonus()
        return mod

    def get_skill_modifier(self, skill: str) -> int:
        ability = SKILL_ABILITIES[skill]
        mod = ability_modifier(self.abilities[ability])
        if skill in self.skill_proficiencies:
            mod += self.get_prof_bonus()
        if skill in self.skill_expertise:
            mod += self.get_prof_bonus()
        return mod

    def toggle_save_proficiency(self, ability: str) -> bool:
        if ability in self.save_proficiencies:
            self.save_proficiencies.remove(ability)
            return False
        self.save_proficiencies.append(ability)
        return True

    def toggle_skill_proficiency(self, skill: str) -> bool:
        if skill in self.skill_proficiencies:
            self.skill_proficiencies.remove(skill)
            self.skill_expertise = [s for s in self.skill_expertise if s != skill]
            return False
        self.skill_proficiencies.append(skill)
        return True

    def toggle_skill_expertise(self, skill: str) -> bool:
        if skill not in self.skill_proficiencies:
            raise ValueError("Skill must be proficient before gaining expertise.")
        if skill in self.skill_expertise:
            self.skill_expertise.remove(skill)
            return False
        self.skill_expertise.append(skill)
        return True

    def set_field(self, field_name: str, value: str) -> None:
        if field_name not in SETTABLE_FIELDS:
            raise ValueError(f"Unknown field: {field_name}")

        if field_name in ABILITIES:
            score = int(value)
            if not 1 <= score <= 30:
                raise ValueError("Ability scores must be between 1 and 30.")
            self.abilities[field_name] = score
            if field_name in {"dex", "con", "wis"}:
                from sheets.armor import apply_armor_ac

                apply_armor_ac(self)
            return

        if field_name == "level":
            level = int(value)
            if not 1 <= level <= 20:
                raise ValueError("Level must be between 1 and 20.")
            self.level = level
            return

        if field_name in {"ac", "speed"}:
            setattr(self, field_name, int(value))
            return

        setattr(self, field_name, value.strip())

    def add_spell(self, slug: str) -> bool:
        slug = normalize_stored_spell_slug(slug)
        if slug in self.spells:
            return False
        self.spells.append(slug)
        return True

    def add_homebrew_spell(self, name: str) -> bool:
        cleaned = name.strip()
        if not cleaned or cleaned in self.homebrew_spells:
            return False
        self.homebrew_spells.append(cleaned)
        return True

    def remove_homebrew_spell(self, name: str) -> bool:
        cleaned = name.strip()
        if cleaned not in self.homebrew_spells:
            return False
        self.homebrew_spells.remove(cleaned)
        return True

    def toggle_condition(self, condition: str) -> bool:
        key = condition.lower().strip()
        if key in self.conditions:
            self.conditions.remove(key)
            return False
        self.conditions.append(key)
        return True

    def reset_death_saves(self) -> None:
        self.death_save_successes = 0
        self.death_save_failures = 0

    def short_rest(self, *, dice_spent: int, healing: int) -> None:
        self.hit_dice_remaining = max(0, self.hit_dice_remaining - dice_spent)
        if self.hp_max:
            self.hp_current = min(self.hp_max, self.hp_current + healing)
        # Warlock pact slots recharge on a short rest.
        if (
            self.char_class.lower().strip().startswith("warlock")
            and self.spell_slots.has_slots()
        ):
            self.spell_slots.restore_all()

    def long_rest(self) -> None:
        self.hp_current = self.hp_max
        self.hit_dice_remaining = self.level
        self.reset_death_saves()
        if self.spell_slots.has_slots():
            self.spell_slots.restore_all()

    def remove_spell(self, slug: str) -> bool:
        slug = normalize_stored_spell_slug(slug)
        if slug not in self.spells:
            return False
        self.spells.remove(slug)
        return True

    def format_spells_summary(self, limit: int = 10) -> str:
        if not self.spells:
            return ""
        names = [slug.replace("-", " ").title() for slug in self.spells[:limit]]
        summary = ", ".join(names)
        if len(self.spells) > limit:
            summary += f" (+{len(self.spells) - limit} more)"
        return summary
