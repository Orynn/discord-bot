import re
from dataclasses import dataclass, field

from sheets.currency import Currency
from sheets.data import ABILITIES, CharacterSheet, ability_modifier, proficiency_bonus
from sheets.equipment import ITEM_KIND_ARMOR, ITEM_KIND_CUSTOM, custom_slug, pack_bundle_contents

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
    equipment_entries: list[tuple[str, int]] = field(default_factory=list)
    equipped_names: list[str] = field(default_factory=list)
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


def _parse_pdf_literal(source: str, start: int) -> tuple[str, int]:
    if start >= len(source) or source[start] != "(":
        return "", start
    index = start + 1
    chars: list[str] = []
    while index < len(source):
        char = source[index]
        if char == "\\" and index + 1 < len(source):
            nxt = source[index + 1]
            if nxt in {"n", "r"}:
                chars.append("\n")
                index += 2
                continue
            if nxt == "t":
                chars.append("\t")
                index += 2
                continue
            chars.append(nxt)
            index += 2
            continue
        if char == ")":
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    return "".join(chars), index


def _field_value_from_block(block: str) -> str | None:
    match = re.search(r"/V\s*", block)
    if not match:
        return None
    index = match.end()
    while index < len(block) and block[index].isspace():
        index += 1
    if index >= len(block) or block[index] != "(":
        return None
    raw, _ = _parse_pdf_literal(block, index)
    return _decode_pdf_string(raw)


def extract_ddb_fields(pdf_bytes: bytes) -> dict[str, str]:
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    fields: dict[str, str] = {}

    for name_match, block in re.findall(r"/T\(([^)]+)\)(.*?)(?=/T\(|$)", raw, re.DOTALL):
        value = _field_value_from_block(block)
        if not value or value in {"Off", "/Off"}:
            continue
        name = _decode_pdf_string(name_match)
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


_QUANTITY_SUFFIX = re.compile(
    r"^(?P<name>.+?)\s*(?:\((?P<qty>\d+)\s*(?:x|×|days?|pcs?|count)?\)|[x×*]\s*(?P<qty2>\d+))\s*$",
    re.IGNORECASE,
)
_QUANTITY_PREFIX = re.compile(r"^(?P<qty>\d+)\s*[x×]\s+(?P<name>.+)$", re.IGNORECASE)
_LEADING_COUNT = re.compile(r"^(?P<qty>\d+)\s+(?P<name>.+)$")
_CURRENCY_LINE = re.compile(r"^\d+\s*(?:cp|sp|ep|gp|pp)\b", re.IGNORECASE)
_CONTAINER_HINTS = (
    "backpack",
    "pouch",
    "bag of",
    "bag",
    "pack",
    "sacoche",
    "bourse",
    "haversack",
    "component pouch",
)


def _is_equipment_field(name: str) -> bool:
    key = re.sub(r"[\s_]+", "", name.casefold())
    if "equipment" in key:
        return True
    return key == "treasure"


def _is_weapon_name_field(name: str) -> bool:
    return bool(re.match(r"^wpn\s*name", name.strip(), re.IGNORECASE))


def _split_comma_items(text: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            piece = "".join(current).strip(" •·\t")
            if piece:
                parts.append(piece)
            current = []
        else:
            current.append(char)
    piece = "".join(current).strip(" •·\t")
    if piece:
        parts.append(piece)
    return parts


def _split_item_blob(text: str) -> list[str]:
    lines: list[str] = []
    for raw in re.split(r"[\r\n]+", text):
        line = re.sub(r"^[\s•·\-\*]+", "", raw).strip()
        if line:
            lines.append(line)
    if len(lines) == 1 and "," in lines[0]:
        return _split_comma_items(lines[0])
    return lines


def parse_equipment_entry(text: str) -> tuple[str, int] | None:
    cleaned = re.sub(r"\s+", " ", text).strip().strip(".")
    if not cleaned or _CURRENCY_LINE.match(cleaned):
        return None
    if cleaned.casefold() in {"equipment", "treasure", "additional equipment", "inventory"}:
        return None

    prefix = _QUANTITY_PREFIX.match(cleaned)
    if prefix:
        return prefix.group("name").strip(), max(1, int(prefix.group("qty")))

    suffix = _QUANTITY_SUFFIX.match(cleaned)
    if suffix:
        quantity = int(suffix.group("qty") or suffix.group("qty2") or 1)
        return suffix.group("name").strip(), max(1, quantity)

    leading = _LEADING_COUNT.match(cleaned)
    if leading:
        name = leading.group("name").strip()
        if name and not name[:1].isdigit():
            return name, max(1, int(leading.group("qty")))

    return cleaned, 1


def _merge_equipment_entries(entries: list[tuple[str, int]]) -> list[tuple[str, int]]:
    merged: dict[str, tuple[str, int]] = {}
    order: list[str] = []
    for name, quantity in entries:
        key = name.casefold()
        if key not in merged:
            merged[key] = (name, quantity)
            order.append(key)
        else:
            original, current = merged[key]
            merged[key] = (original, current + quantity)
    return [merged[key] for key in order]


def _likely_container(name: str) -> bool:
    lowered = name.casefold()
    return any(hint in lowered for hint in _CONTAINER_HINTS)


def collect_equipment_entries(fields: dict[str, str]) -> list[tuple[str, int]]:
    blobs: list[str] = []
    for name, value in fields.items():
        if _is_equipment_field(name):
            blobs.append(value)
    entries: list[tuple[str, int]] = []
    for blob in blobs:
        for piece in _split_item_blob(blob):
            parsed = parse_equipment_entry(piece)
            if parsed is not None:
                entries.append(parsed)
    return _merge_equipment_entries(entries)


def collect_equipped_names(fields: dict[str, str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for field_name, value in fields.items():
        if not _is_weapon_name_field(field_name):
            continue
        cleaned = re.sub(r"\s+", " ", value).strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            names.append(cleaned)
    return names


async def add_catalog_equipment(sheet: CharacterSheet, entry: dict, quantity: int = 1) -> tuple[int, int, list[str]]:
    from srd import fivetools

    pieces = pack_bundle_contents(entry)
    if pieces is None:
        sheet.equipment.add_item(
            slug=entry["slug"],
            name=entry["name"],
            kind=entry["kind"],
            quantity=quantity,
            weight_lb=entry.get("weight_lb"),
        )
        fivetools.register_glossary_item(
            item=entry,
            endpoint={"weapon": "weapons", "armor": "armor", "item": "items"}[entry["kind"]],
        )
        return 1, 0, [entry["name"]]

    matched = 0
    custom = 0
    names: list[str] = []
    for piece_name, piece_qty in pieces:
        try:
            piece = await fivetools.search_equipment(query=piece_name)
        except fivetools.Open5eError:
            sheet.equipment.add_item(
                slug=custom_slug(piece_name),
                name=piece_name.title(),
                kind=ITEM_KIND_CUSTOM,
                quantity=piece_qty * quantity,
            )
            custom += 1
            names.append(piece_name.title())
            continue
        sheet.equipment.add_item(
            slug=piece["slug"],
            name=piece["name"],
            kind=piece["kind"],
            quantity=piece_qty * quantity,
            weight_lb=piece.get("weight_lb"),
        )
        fivetools.register_glossary_item(
            item=piece,
            endpoint={"weapon": "weapons", "armor": "armor", "item": "items"}[piece["kind"]],
        )
        matched += 1
        names.append(piece["name"])
    return matched, custom, names


async def fill_sheet_equipment(
    sheet: CharacterSheet,
    *,
    entries: list[tuple[str, int]],
    equipped_names: list[str],
) -> tuple[int, int]:
    from srd import fivetools

    pending = list(entries)
    seen = {name.casefold() for name, _qty in pending}
    for name in equipped_names:
        if name.casefold() not in seen:
            pending.append((name, 1))
            seen.add(name.casefold())

    pending.sort(key=lambda item: (0 if _likely_container(item[0]) else 1, item[0].casefold()))
    matched = 0
    custom = 0
    for name, quantity in pending:
        try:
            entry = await fivetools.search_equipment(query=name)
        except fivetools.Open5eNotFoundError:
            sheet.equipment.add_item(
                slug=custom_slug(name),
                name=name,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
            )
            custom += 1
            continue
        except fivetools.Open5eError:
            sheet.equipment.add_item(
                slug=custom_slug(name),
                name=name,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
            )
            custom += 1
            continue
        added, added_custom, _names = await add_catalog_equipment(sheet, entry, quantity)
        matched += added
        custom += added_custom

    for item in list(sheet.equipment.items):
        if item.kind != ITEM_KIND_ARMOR:
            continue
        if sheet.equipment.is_shield(item):
            continue
        try:
            sheet.equipment.equip(item.name)
        except ValueError:
            pass

    for item in list(sheet.equipment.items):
        if not sheet.equipment.is_shield(item):
            continue
        try:
            sheet.equipment.equip(item.name)
        except ValueError:
            pass

    for name in equipped_names:
        try:
            sheet.equipment.equip(name)
        except ValueError:
            pass

    from sheets.armor import apply_armor_ac

    apply_armor_ac(sheet)
    return matched, custom


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
    equipment_entries = collect_equipment_entries(fields)
    equipped_names = collect_equipped_names(fields)
    if not name:
        warnings.append("Character name was missing; using 'Unknown'.")

    return DdbPdfImport(
        sheet=sheet,
        spell_names=spell_names,
        equipment_entries=equipment_entries,
        equipped_names=equipped_names,
        warnings=warnings,
    )


def format_import_summary(
    *,
    sheet: CharacterSheet,
    spell_count: int,
    homebrew_count: int = 0,
    gear_count: int = 0,
    custom_gear_count: int = 0,
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
        f"Spells **{spell_count}** · Gear **{gear_count}**",
    ]

    if warnings:
        lines.append("Warnings: " + "; ".join(warnings))

    if homebrew_count:
        lines.append(f"Homebrew spells saved (not in SRD): **{homebrew_count}**")

    if custom_gear_count:
        lines.append(f"Custom gear (not in 5etools): **{custom_gear_count}**")

    return "\n".join(lines)
