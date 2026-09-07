import re
import zlib
from dataclasses import dataclass, field

from sheets.armor import apply_armor_ac
from sheets.currency import Currency
from sheets.data import (
    ABILITIES,
    SKILL_ABILITIES,
    CharacterSheet,
    ability_modifier,
    proficiency_bonus,
)
from sheets.equipment import (
    ITEM_KIND_ARMOR,
    ITEM_KIND_CUSTOM,
    ITEM_KIND_WEAPON,
    custom_slug,
    pack_bundle_contents,
)
from sheets.spell_slots import slots_table_for_class
from srd.fivetools_parser import parse_weight_lb

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
    "SleightofHandProf": "sleight_of_hand",
    "SleightOfHandProf": "sleight_of_hand",
    "SurvivalProf": "survival",
}

DDB_SKILL_SCORE_FIELDS: dict[str, str] = {
    "Acrobatics": "acrobatics",
    "Animal": "animal_handling",
    "Arcana": "arcana",
    "Athletics": "athletics",
    "Deception": "deception",
    "History": "history",
    "Insight": "insight",
    "Intimidation": "intimidation",
    "Investigation": "investigation",
    "Medicine": "medicine",
    "Nature": "nature",
    "Perception": "perception",
    "Performance": "performance",
    "Persuasion": "persuasion",
    "Religion": "religion",
    "SleightofHand": "sleight_of_hand",
    "Stealth": "stealth",
    "Survival": "survival",
}

DDB_SAVE_PROF_FIELDS: dict[str, str] = {
    "StrProf": "str",
    "DexProf": "dex",
    "ConProf": "con",
    "IntProf": "int",
    "WisProf": "wis",
    "ChaProf": "cha",
}

_PROF_MARKERS = frozenset({"P", "O", "YES", "Y", "•", "●", "X", "ON", "TRUE", "1"})
_EXPERTISE_MARKERS = frozenset({"E"})
_SKILL_PROF_STEMS: dict[str, str] = {
    "acrobatics": "acrobatics",
    "animal": "animal_handling",
    "animalhandling": "animal_handling",
    "arcana": "arcana",
    "athletics": "athletics",
    "deception": "deception",
    "history": "history",
    "insight": "insight",
    "intimidation": "intimidation",
    "investigation": "investigation",
    "medicine": "medicine",
    "nature": "nature",
    "perception": "perception",
    "performance": "performance",
    "persuasion": "persuasion",
    "religion": "religion",
    "sleight": "sleight_of_hand",
    "sleightofhand": "sleight_of_hand",
    "stealth": "stealth",
    "survival": "survival",
}
_SAVE_PROF_STEMS: dict[str, str] = {
    "strprof": "str",
    "dexprof": "dex",
    "conprof": "con",
    "intprof": "int",
    "wisprof": "wis",
    "chaprof": "cha",
}
_SKIP_TRAIT_TITLES = frozenset(
    {
        "creature type",
        "size",
        "speed",
        "languages",
        "soldier ability score improvements",
    }
)
_NOTES_LIMIT = 2000


@dataclass
class DdbPdfImport:
    sheet: CharacterSheet
    spell_names: list[str] = field(default_factory=list)
    equipment_entries: list[tuple[str, int]] = field(default_factory=list)
    equipped_names: list[str] = field(default_factory=list)
    equipment_weights: dict[str, float] = field(default_factory=dict)
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


def _skip_ws(source: str, index: int) -> int:
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _parse_pdf_hex_string(source: str, start: int) -> tuple[str, int]:
    if start >= len(source) or source[start] != "<":
        return "", start
    end = source.find(">", start + 1)
    if end == -1:
        return "", start
    hexdigits = re.sub(r"\s+", "", source[start + 1 : end])
    if len(hexdigits) % 2:
        hexdigits += "0"
    try:
        raw = bytes.fromhex(hexdigits)
    except ValueError:
        return "", end + 1
    if raw.startswith(b"\xfe\xff"):
        text = raw[2:].decode("utf-16-be", errors="replace")
    elif raw.startswith(b"\xff\xfe"):
        text = raw[2:].decode("utf-16-le", errors="replace")
    else:
        text = raw.decode("latin-1", errors="replace")
    return _decode_pdf_string(text), end + 1


def _parse_pdf_string_token(source: str, start: int) -> tuple[str | None, int]:
    index = _skip_ws(source, start)
    if index >= len(source):
        return None, index
    if source[index] == "(":
        text, nxt = _parse_pdf_literal(source, index)
        return _decode_pdf_string(text), nxt
    if source[index] == "<" and (index + 1 >= len(source) or source[index + 1] != "<"):
        text, nxt = _parse_pdf_hex_string(source, index)
        return text, nxt
    return None, index


def _index_pdf_objects(raw: str) -> dict[int, str]:
    objects: dict[int, str] = {}
    for match in re.finditer(r"(\d+)\s+0\s+obj\b", raw):
        start = match.end()
        end = raw.find("endobj", start)
        if end == -1:
            continue
        objects[int(match.group(1))] = raw[start:end]
    return objects


def _inflate_stream(body: str) -> str | None:
    stream_match = re.search(r"stream\r?\n", body)
    if not stream_match:
        return None
    end = body.rfind("endstream")
    if end == -1:
        return None
    data = body[stream_match.end() : end]
    if data.endswith("\r\n"):
        data = data[:-2]
    elif data.endswith(("\n", "\r")):
        data = data[:-1]
    raw_bytes = data.encode("latin-1")
    if "FlateDecode" in body[: stream_match.start()]:
        try:
            raw_bytes = zlib.decompress(raw_bytes)
        except zlib.error:
            return None
    return raw_bytes.decode("latin-1", errors="replace")


def _string_from_object(body: str) -> str | None:
    parsed, _ = _parse_pdf_string_token(body, 0)
    if parsed:
        return parsed
    for match in re.finditer(r"\(|<(?!<)", body):
        parsed, _ = _parse_pdf_string_token(body, match.start())
        if parsed:
            return parsed
    inflated = _inflate_stream(body)
    if not inflated:
        return None
    for match in re.finditer(r"\(|<(?!<)", inflated):
        parsed, _ = _parse_pdf_string_token(inflated, match.start())
        if parsed:
            return parsed
    cleaned = inflated.strip()
    return cleaned or None


def _value_after_v(source: str, v_end: int, objects: dict[int, str]) -> str | None:
    index = _skip_ws(source, v_end)
    parsed, _ = _parse_pdf_string_token(source, index)
    if parsed is not None:
        return parsed
    ref = re.match(r"(\d+)\s+\d+\s+R", source[index:])
    if not ref:
        return None
    body = objects.get(int(ref.group(1)))
    if not body:
        return None
    return _string_from_object(body)


def _first_pdf_value(block: str, objects: dict[int, str]) -> str | None:
    for match in re.finditer(r"/V(?![A-Za-z0-9])\s*", block):
        value = _value_after_v(block, match.end(), objects)
        if value:
            return value
    return None


def _next_field_name(raw: str, start: int) -> int:
    match = re.search(r"/T(?![A-Za-z0-9])\s*", raw[start:])
    if match is None:
        return min(len(raw), start + 900)
    return start + match.start()


def extract_ddb_fields(pdf_bytes: bytes) -> dict[str, str]:
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    objects = _index_pdf_objects(raw)
    fields: dict[str, str] = {}

    for match in re.finditer(r"/T(?![A-Za-z0-9])\s*", raw):
        name, after_name = _parse_pdf_string_token(raw, match.end())
        if not name:
            continue
        fwd_end = _next_field_name(raw, after_name)
        dict_end = raw.find(">>", after_name)
        if dict_end != -1:
            fwd_end = min(fwd_end, dict_end)
        forward = raw[after_name:fwd_end]
        value = _first_pdf_value(forward, objects)
        if not value:
            dict_start = raw.rfind("<<", max(0, match.start() - 4000), match.start())
            dict_end = raw.find(">>", match.end())
            if dict_start != -1 and dict_end != -1 and dict_end > dict_start:
                value = _first_pdf_value(raw[dict_start:dict_end], objects)
            else:
                value = _first_pdf_value(
                    raw[max(0, match.start() - 200) : match.start()], objects
                )
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


def _fold_field(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).casefold()


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_prof_marker(value: str) -> bool:
    return value.strip().upper() in _PROF_MARKERS


def _first_field(fields: dict[str, str], *names: str) -> str:
    for name in names:
        value = fields.get(name, "").strip()
        if value and value not in {"--", "-", "—"}:
            return value
    return ""


def _character_name(fields: dict[str, str]) -> str:
    name = fields.get("CharacterName", "").strip()
    player = fields.get("PLAYER NAME", "").strip()
    if player:
        placeholder = f"{player}'s Character"
        if not name or name.casefold() == placeholder.casefold():
            return player
    return name or player or "Unknown"


def _skill_from_prof_field(field_name: str) -> str | None:
    if field_name in DDB_SKILL_FIELDS:
        return DDB_SKILL_FIELDS[field_name]
    folded = _fold_field(field_name)
    if not folded.endswith("prof"):
        return None
    return _SKILL_PROF_STEMS.get(folded[:-4])


def _collect_save_proficiencies(
    fields: dict[str, str], sheet: CharacterSheet
) -> list[str]:
    prof_bonus = proficiency_bonus(sheet.level)
    proficiencies: list[str] = []
    seen: set[str] = set()

    def add(ability: str) -> None:
        if ability not in seen:
            seen.add(ability)
            proficiencies.append(ability)

    for field_name, ability in DDB_SAVE_FIELDS.items():
        modifier = _parse_modifier(fields.get(field_name, ""))
        if modifier is None:
            continue

        base = ability_modifier(sheet.abilities[ability])
        if modifier >= base + prof_bonus:
            add(ability)

    for field_name, ability in DDB_SAVE_PROF_FIELDS.items():
        if _is_prof_marker(fields.get(field_name, "")):
            add(ability)

    for field_name, value in fields.items():
        ability = _SAVE_PROF_STEMS.get(_fold_field(field_name))
        if ability and _is_prof_marker(value):
            add(ability)

    return proficiencies


def _collect_skill_proficiencies(
    fields: dict[str, str], sheet: CharacterSheet
) -> tuple[list[str], list[str]]:
    proficiencies: list[str] = []
    expertise: list[str] = []
    seen_prof: set[str] = set()
    seen_exp: set[str] = set()

    def add(skill: str, *, expert: bool = False) -> None:
        if skill not in seen_prof:
            seen_prof.add(skill)
            proficiencies.append(skill)
        if expert and skill not in seen_exp:
            seen_exp.add(skill)
            expertise.append(skill)

    for field_name, value in fields.items():
        skill = _skill_from_prof_field(field_name)
        if not skill:
            continue
        marker = value.strip().upper()
        if marker in _EXPERTISE_MARKERS:
            add(skill, expert=True)
        elif _is_prof_marker(value):
            add(skill)

    prof_bonus = proficiency_bonus(sheet.level)
    for field_name, skill in DDB_SKILL_SCORE_FIELDS.items():
        if skill in seen_prof:
            continue
        modifier = _parse_modifier(fields.get(field_name, ""))
        if modifier is None:
            continue
        ability = SKILL_ABILITIES[skill]
        base = ability_modifier(sheet.abilities[ability])
        if modifier >= base + (2 * prof_bonus):
            add(skill, expert=True)
        elif modifier >= base + prof_bonus:
            add(skill)

    return proficiencies, expertise


def _proficiency_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for match in re.finditer(
        r"===\s*(?P<header>[^=]+?)\s*===\s*(?P<body>.*?)(?=\n===|\Z)",
        text,
        re.S,
    ):
        header = _one_line(match.group("header")).casefold()
        body = _one_line(match.group("body"))
        if body:
            sections[header] = body
    return sections


def _feature_titles(fields: dict[str, str]) -> list[str]:
    chunks: list[str] = []
    for key, value in fields.items():
        folded = _fold_field(key)
        if folded.startswith("featurestraits") or folded.startswith(
            "featuresandtraits"
        ):
            chunks.append(value)
    titles: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"^\*\s+(.+?)(?:\s+•|\s*$)", "\n".join(chunks), re.M):
        title = _one_line(match.group(1))
        key = title.casefold()
        if not title or key in _SKIP_TRAIT_TITLES or key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def _collect_notes(fields: dict[str, str]) -> str:
    parts: list[str] = []
    identity: list[str] = []
    alignment = _first_field(fields, "ALIGNMENT", "Alignment")
    if alignment:
        identity.append(alignment)
    gender = _first_field(fields, "GENDER", "Gender")
    if gender:
        identity.append(gender)
    age = _first_field(fields, "AGE", "Age")
    if age:
        identity.append(f"{age} ans" if age.isdigit() else age)
    height = _first_field(fields, "HEIGHT", "Height")
    if height:
        identity.append(height)
    weight = _first_field(fields, "WEIGHT", "Weight")
    if weight:
        identity.append(weight)
    size = _first_field(fields, "SIZE", "Size")
    if size:
        identity.append(size)
    looks: list[str] = []
    eyes = _first_field(fields, "EYES", "Eyes")
    if eyes:
        looks.append(f"yeux {eyes}")
    skin = _first_field(fields, "SKIN", "Skin")
    if skin:
        looks.append(f"peau {skin}")
    identity.extend(looks)
    if identity:
        parts.append(" · ".join(identity))

    faith = _first_field(fields, "FAITH", "Faith")
    if faith:
        parts.append(f"Foi : {faith}")
    senses = _first_field(fields, "AdditionalSenses", "Senses")
    if senses:
        parts.append(f"Sens : {senses}")
    defenses = _first_field(fields, "Defenses", "Defence", "Defense")
    if defenses:
        parts.append(f"Défenses : {defenses}")

    sections = _proficiency_sections(fields.get("ProficienciesLang", ""))
    labels = (
        ("armor", "Armures"),
        ("weapons", "Armes"),
        ("tools", "Outils"),
        ("languages", "Langues"),
    )
    for key, label in labels:
        body = sections.get(key, "")
        if body:
            parts.append(f"{label} : {body}")

    traits = _feature_titles(fields)
    if traits:
        parts.append("Traits : " + ", ".join(traits))

    notes = "\n".join(parts)
    return notes[:_NOTES_LIMIT]


def _parse_inspired(fields: dict[str, str]) -> bool:
    for name in ("Inspiration", "Inspired", "Heroic Inspiration"):
        if _is_prof_marker(fields.get(name, "")):
            return True
    return False


def _apply_class_spell_slots(sheet: CharacterSheet) -> None:
    level = min(20, max(1, sheet.level))
    try:
        table = slots_table_for_class(sheet.char_class, level, subclass=sheet.subclass)
    except ValueError:
        return
    if table is not None:
        sheet.spell_slots.apply_table(table)


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
    return any(token in key for token in ("equipment", "treasure", "inventory"))


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
    if cleaned.casefold() in {
        "equipment",
        "treasure",
        "additional equipment",
        "inventory",
    }:
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


_EQ_NAME_FIELD = re.compile(r"^eq\s*name\s*(\d+)$", re.IGNORECASE)
_EQ_QTY_FIELD = re.compile(r"^eq\s*qty\s*(\d+)$", re.IGNORECASE)
_EQ_WEIGHT_FIELD = re.compile(r"^eq\s*weight\s*(\d+)$", re.IGNORECASE)
_ATTACK_ONLY = frozenset({"unarmed strike", "unarmed", "fist"})


def _parse_eq_table(
    fields: dict[str, str],
) -> tuple[list[tuple[str, int]], dict[str, float]]:
    names: dict[str, str] = {}
    quantities: dict[str, int] = {}
    raw_weights: dict[str, str] = {}
    for field_name, value in fields.items():
        named = _EQ_NAME_FIELD.match(field_name.strip())
        if named:
            cleaned = re.sub(r"\s+", " ", value).strip()
            if cleaned:
                names[named.group(1)] = cleaned
            continue
        counted = _EQ_QTY_FIELD.match(field_name.strip())
        if counted:
            quantities[counted.group(1)] = max(1, _parse_int(value, default=1))
            continue
        weighed = _EQ_WEIGHT_FIELD.match(field_name.strip())
        if weighed:
            raw_weights[weighed.group(1)] = value
    entries = [
        (names[index], quantities.get(index, 1))
        for index in sorted(names, key=lambda key: int(key))
    ]
    weights: dict[str, float] = {}
    for index, name in names.items():
        parsed = parse_weight_lb(raw_weights.get(index, ""))
        if parsed is not None:
            weights[name.casefold()] = parsed
    return entries, weights


def _collect_eq_table_entries(fields: dict[str, str]) -> list[tuple[str, int]]:
    entries, _weights = _parse_eq_table(fields)
    return entries


def collect_equipment_weights(fields: dict[str, str]) -> dict[str, float]:
    _entries, weights = _parse_eq_table(fields)
    return weights


def collect_equipment_entries(fields: dict[str, str]) -> list[tuple[str, int]]:
    entries = list(_collect_eq_table_entries(fields))
    blobs: list[str] = []
    for name, value in fields.items():
        if _is_equipment_field(name):
            blobs.append(value)
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


async def add_catalog_equipment(
    sheet: CharacterSheet, entry: dict, quantity: int = 1
) -> tuple[int, int, list[str]]:
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
            endpoint={"weapon": "weapons", "armor": "armor", "item": "items"}[
                entry["kind"]
            ],
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
            endpoint={"weapon": "weapons", "armor": "armor", "item": "items"}[
                piece["kind"]
            ],
        )
        matched += 1
        names.append(piece["name"])
    return matched, custom, names


async def fill_sheet_equipment(
    sheet: CharacterSheet,
    *,
    entries: list[tuple[str, int]],
    equipped_names: list[str],
    weights: dict[str, float] | None = None,
) -> tuple[int, int]:
    from srd import fivetools

    pending = list(entries)
    seen = {name.casefold() for name, _qty in pending}
    for name in equipped_names:
        if name.casefold() not in seen:
            pending.append((name, 1))
            seen.add(name.casefold())

    pending.sort(
        key=lambda item: (0 if _likely_container(item[0]) else 1, item[0].casefold())
    )
    matched = 0
    custom = 0
    item_weights = weights or {}
    for name, quantity in pending:
        try:
            entry = await fivetools.search_equipment(query=name)
        except fivetools.Open5eNotFoundError:
            sheet.equipment.add_item(
                slug=custom_slug(name),
                name=name,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
                weight_lb=item_weights.get(name.casefold()),
            )
            custom += 1
            continue
        except fivetools.Open5eError:
            sheet.equipment.add_item(
                slug=custom_slug(name),
                name=name,
                kind=ITEM_KIND_CUSTOM,
                quantity=quantity,
                weight_lb=item_weights.get(name.casefold()),
            )
            custom += 1
            continue
        added, added_custom, _names = await add_catalog_equipment(
            sheet, entry, quantity
        )
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

    has_held_weapon = any(
        item.kind == ITEM_KIND_WEAPON and item.equipped
        for item in sheet.equipment.items
    )
    if not has_held_weapon:
        for name, _quantity in entries:
            item = sheet.equipment.find_item(name)
            if item is None or item.kind != ITEM_KIND_WEAPON:
                continue
            try:
                sheet.equipment.equip(item.name)
            except ValueError:
                continue
            break

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

    name = _character_name(fields)
    char_class, level, subclass = _parse_class_and_level(
        fields.get("CLASS  LEVEL", fields.get("CLASS  LEVEL2", "Adventurer 1"))
    )

    abilities = dict.fromkeys(ABILITIES, 10)
    for ddb_key, ability in DDB_ABILITY_FIELDS.items():
        if ddb_key in fields:
            abilities[ability] = _parse_int(fields[ddb_key], default=10)

    hp_max = _parse_int(_first_field(fields, "MaxHP", "HPMax", "HP Maximum") or "0")
    hp_current = _parse_int(
        _first_field(fields, "CurrentHP", "HPCurrent", "HP") or str(hp_max or 0)
    )
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
        ac=_parse_int(_first_field(fields, "AC") or "10", default=10),
        speed=_parse_speed(_first_field(fields, "Speed") or "30 ft."),
        spells=[],
        currency=currency,
        notes=_collect_notes(fields),
        inspired=_parse_inspired(fields),
    )
    _apply_class_spell_slots(sheet)

    sheet.save_proficiencies = _collect_save_proficiencies(fields, sheet)
    sheet.skill_proficiencies, sheet.skill_expertise = _collect_skill_proficiencies(
        fields, sheet
    )

    spell_names = _collect_spell_names(fields)
    equipment_entries = collect_equipment_entries(fields)
    equipment_weights = collect_equipment_weights(fields)
    spells_folded = {name.casefold() for name in spell_names}
    equipped_names = [
        name
        for name in collect_equipped_names(fields)
        if name.casefold() not in _ATTACK_ONLY and name.casefold() not in spells_folded
    ]
    if not name or name == "Unknown":
        warnings.append("Character name was missing; using 'Unknown'.")
    if not equipment_entries and not equipped_names:
        warnings.append("Aucun équipement lisible dans ce PDF.")

    return DdbPdfImport(
        sheet=sheet,
        spell_names=spell_names,
        equipment_entries=equipment_entries,
        equipped_names=equipped_names,
        equipment_weights=equipment_weights,
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
