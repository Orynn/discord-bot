import re
from dataclasses import dataclass, field

from sheets.currency import Currency
from sheets.data import ABILITIES, CharacterSheet, ability_modifier, proficiency_bonus

DDB_ABILITY_FIELDS: dict[str, str] = {
    "STR": "str",
    "DEX": "dex",
    "CON": "con",
    "INT": "int",
    "WIS": "wis",
    "CHA": "cha",
}

DDB_SAVE_FIELDS: dict[str, str] = {
    "ST Strength": "str",
    "ST Dexterity": "dex",
    "ST Constitution": "con",
    "ST Intelligence": "int",
    "ST Wisdom": "wis",
    "ST Charisma": "cha",
}

DDB_SKILL_FIELDS: dict[str, str] = {
    "AcrobaticsProf": "acrobatics",
    "AnimalProf": "animal_handling",
    "ArcanaProf": "arcana",
    "AthleticsProf": "athletics",
    "DeceptionProf": "deception",
    "HistoryProf": "history",
    "InsightProf": "insight",
    "IntimidationProf": "intimidation",
    "InvestigationProf": "investigation",
    "MedicineProf": "medicine",
    "NatureProf": "nature",
    "PerceptionProf": "perception",
    "PerformanceProf": "performance",
    "PersuasionProf": "persuasion",
    "ReligionProf": "religion",
    "StealthProf": "stealth",
    "SleightProf": "sleight_of_hand",
    "SurvivalProf": "survival",
}


@dataclass
class DdbPdfImport:
    sheet: CharacterSheet
    spell_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _decode_pdf_string(value: str) -> str:
    return (
        value.replace("\\(", "(")
        .replace("\\)", ")")
        .replace("\\\\", "\\")
        .replace("\\220", "-")
        .replace("\\(", "(")
        .strip()
    )


def extract_ddb_fields(pdf_bytes: bytes) -> dict[str, str]:
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    fields: dict[str, str] = {}

    for name_match, block in re.findall(r"/T\(([^)]+)\)(.*?)(?=/T\(|$)", raw, re.DOTALL):
        value_match = re.search(r"/V\(([^)]*)\)", block)
        if not value_match:
            continue

        name = _decode_pdf_string(name_match)
        value = _decode_pdf_string(value_match.group(1))
        if not value or value in {"Off", "/Off"}:
            continue

        if name not in fields:
            fields[name] = value

    return fields


def _parse_int(value: str, default: int = 0) -> int:
    match = re.search(r"-?\d+", value)
    return int(match.group(0)) if match else default


def _parse_modifier(value: str) -> int | None:
    match = re.search(r"[+-]?\d+", value)
    return int(match.group(0)) if match else None


def _parse_class_and_level(raw: str) -> tuple[str, int, str]:
    cleaned = raw.strip()
    subclass = ""

    subclass_match = re.search(r"\(([^)]+)\)", cleaned)
    if subclass_match:
        subclass = subclass_match.group(1).strip()
        cleaned = cleaned[: subclass_match.start()].strip()

    match = re.match(r"^(.+?)\s+(\d+)\s*$", cleaned)
    if match:
        return match.group(1).strip(), int(match.group(2)), subclass

    return cleaned, 1, subclass


def _parse_speed(raw: str) -> int:
    match = re.search(r"(\d+)\s*ft", raw, re.IGNORECASE)
    return int(match.group(1)) if match else 30


def _collect_save_proficiencies(fields: dict[str, str], sheet: CharacterSheet) -> list[str]:
    prof_bonus = proficiency_bonus(sheet.level)
    proficiencies: list[str] = []

    for field_name, ability in DDB_SAVE_FIELDS.items():
        modifier = _parse_modifier(fields.get(field_name, ""))
        if modifier is None:
            continue

        base = ability_modifier(sheet.abilities[ability])
        if modifier >= base + prof_bonus:
            proficiencies.append(ability)

    return proficiencies


def _collect_skill_proficiencies(fields: dict[str, str]) -> tuple[list[str], list[str]]:
    proficiencies: list[str] = []
    expertise: list[str] = []

    for field_name, skill in DDB_SKILL_FIELDS.items():
        marker = fields.get(field_name, "").strip().upper()
        if marker in {"P", "O", "YES", "Y"}:
            proficiencies.append(skill)
        if marker == "E":
            proficiencies.append(skill)
            expertise.append(skill)

    return proficiencies, expertise


def _collect_spell_names(fields: dict[str, str]) -> list[str]:
    names: list[str] = []
    for index in range(200):
        raw = fields.get(f"spellName{index}", "").strip()
        if not raw:
            continue
        cleaned = re.sub(r"\s*\[[A-Z]\]\s*$", "", raw).strip()
        if cleaned:
            names.append(cleaned)
    return names


def parse_ddb_pdf(pdf_bytes: bytes) -> DdbPdfImport:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("File does not appear to be a valid PDF.")

    fields = extract_ddb_fields(pdf_bytes)
    warnings: list[str] = []

    if not fields.get("CharacterName") and not fields.get("CLASS  LEVEL"):
        raise ValueError(
            "This PDF does not look like a D&D Beyond character sheet export."
        )

    name = fields.get("CharacterName", "Unknown").strip()
    char_class, level, subclass = _parse_class_and_level(
        fields.get("CLASS  LEVEL", fields.get("CLASS  LEVEL2", "Adventurer 1"))
    )

    abilities = dict.fromkeys(ABILITIES, 10)
    for ddb_key, ability in DDB_ABILITY_FIELDS.items():
        if ddb_key in fields:
            abilities[ability] = _parse_int(fields[ddb_key], default=10)

    hp_max = _parse_int(fields.get("MaxHP", "0"))
    hp_current = _parse_int(fields.get("CurrentHP", str(hp_max or 0)))
    if hp_current <= 0 and hp_max > 0:
        hp_current = hp_max

    currency = Currency(
        cp=_parse_int(fields.get("CP", "0")),
        sp=_parse_int(fields.get("SP", "0")),
        ep=_parse_int(fields.get("EP", "0")),
        gp=_parse_int(fields.get("GP", "0")),
        pp=_parse_int(fields.get("PP", "0")),
    )

    sheet = CharacterSheet(
        name=name,
        species=fields.get("RACE", fields.get("SPECIES", "")).strip(),
        char_class=char_class,
        subclass=subclass,
        level=level,
        background=fields.get("BACKGROUND", "").strip(),
        abilities=abilities,
        hp_max=hp_max,
        hp_current=hp_current,
        ac=_parse_int(fields.get("AC", "10"), default=10),
        speed=_parse_speed(fields.get("Speed", "30 ft.")),
        spells=[],
        currency=currency,
    )

    sheet.save_proficiencies = _collect_save_proficiencies(fields, sheet)
    sheet.skill_proficiencies, sheet.skill_expertise = _collect_skill_proficiencies(fields)

    spell_names = _collect_spell_names(fields)
    if not name:
        warnings.append("Character name was missing; using 'Unknown'.")

    return DdbPdfImport(sheet=sheet, spell_names=spell_names, warnings=warnings)


def format_import_summary(
    *,
    sheet: CharacterSheet,
    spell_count: int,
    homebrew_count: int = 0,
    warnings: list[str],
) -> str:
    class_line = sheet.char_class
    if sheet.subclass:
        class_line = f"{sheet.char_class} ({sheet.subclass})"

    lines = [
        f"Imported **{sheet.name}** from D&D Beyond PDF.",
        (
            f"**{class_line}** · Level **{sheet.level}** · "
            f"**{sheet.species or '—'}** · **{sheet.background or '—'}**"
        ),
        f"HP **{sheet.hp_current}/{sheet.hp_max}** · AC **{sheet.ac}** · "
        f"Speed **{sheet.speed} ft.** · **{sheet.currency.format()}**",
        f"Skills **{len(sheet.skill_proficiencies)}** · Saves **{len(sheet.save_proficiencies)}** · "
        f"Spells **{spell_count}**",
    ]

    if warnings:
        lines.append("Warnings: " + "; ".join(warnings))

    if homebrew_count:
        lines.append(f"Homebrew spells saved (not in SRD): **{homebrew_count}**")

    return "\n".join(lines)
