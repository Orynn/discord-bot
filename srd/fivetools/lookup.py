from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

from srd.fivetools.edition import edition_rank, url_target
from srd.fivetools.loader import FiveToolsIndex, ensure_index_loaded, get_index, peek_index
from srd.fivetools_parser import (
    clean_tags,
    damage_type,
    format_components,
    format_cost,
    format_damage_type_label,
    format_duration,
    format_range,
    format_spell_level,
    format_time,
    format_weight,
    render_entries,
    slugify,
    spell_school,
)

FIVETOOLS_WEB = "https://5e.tools"
DEFAULT_SOURCE = "XPHB"
SRD_SLUG = DEFAULT_SOURCE

_KIND_PAGES = {
    "spell": "spells",
    "species": "races",
    "class": "classes",
    "subclass": "classes",
    "background": "backgrounds",
    "condition": "conditionsdiseases",
    "feat": "feats",
    "weapon": "items",
    "armor": "items",
    "item": "items",
    "skill": "skills",
    "monster": "bestiary",
}


class FiveToolsError(Exception):
    pass


class FiveToolsNotFoundError(FiveToolsError):
    pass


# Backward-compatible aliases while callers migrate.
Open5eError = FiveToolsError
Open5eNotFoundError = FiveToolsNotFoundError

_RENDER_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_RENDER_CACHE_MAX = 256

_KIND_NAME_STORES = {
    "spell": "spells_by_name",
    "species": "races_by_name",
    "class": "classes_by_name",
    "background": "backgrounds_by_name",
    "feat": "feats_by_name",
    "condition": "conditions_by_name",
    "weapon": "weapons_by_name",
    "armor": "armor_by_name",
    "item": "items_by_name",
    "monster": "monsters_by_name",
    "skill": "skills_by_name",
}


def clear_render_cache() -> None:
    _RENDER_CACHE.clear()


def _cache_get(kind: str, identity: str) -> dict[str, Any] | None:
    return _RENDER_CACHE.get((kind, identity.lower()))


def _cache_put(kind: str, identity: str, item: dict[str, Any]) -> None:
    if len(_RENDER_CACHE) >= _RENDER_CACHE_MAX:
        _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
    _RENDER_CACHE[(kind, identity.lower())] = item


def close_session() -> None:
    return None


async def warm_index() -> None:
    await ensure_index_loaded()


def short_slug(key: str) -> str:
    for prefix in ("srd-2024_", "wotc-srd_", f"{DEFAULT_SOURCE.lower()}_"):
        if key.startswith(prefix):
            return key[len(prefix) :]
    if "|" in key:
        return slugify(key.split("|", 1)[0])
    return slugify(key)


def api_key(slug: str, source: str = DEFAULT_SOURCE) -> str:
    return f"{slugify(slug)}_{source.lower()}"


def _item_source(item: dict[str, Any]) -> str:
    return str(item.get("source") or DEFAULT_SOURCE)


def item_source(item: dict[str, Any]) -> str:
    return _item_source(item)


def _document_fields(item: dict[str, Any], *, slug: str | None = None, kind: str = "item") -> dict[str, Any]:
    source = _item_source(item)
    resolved_slug = slug or item.get("slug") or slugify(item["name"])
    index = get_index()
    return {
        "key": api_key(resolved_slug, source),
        "document__slug": source,
        "document__title": index.source_title(source),
        "url": entry_url_for_item(kind, item),
    }


def page_url(page: str, name: str, *, source: str = DEFAULT_SOURCE) -> str:
    anchor = f"{quote(name.lower())}_{source.lower()}"
    return f"{FIVETOOLS_WEB}/{page}.html#{anchor}"


def _page_for_kind(kind: str) -> str:
    return _KIND_PAGES.get(kind, "items")


def entry_url(kind: str, name: str, *, source: str = DEFAULT_SOURCE) -> str:
    name, resolved_source = url_target({"name": name, "source": source})
    return page_url(_page_for_kind(kind), name, source=resolved_source)


def entry_url_for_item(kind: str, item: dict[str, Any]) -> str:
    name, source = url_target(item)
    return page_url(_page_for_kind(kind), name, source=source)


def _pick_best_match(items: Iterable[dict[str, Any]], query: str) -> dict[str, Any] | None:
    query_lower = query.lower().strip()
    if not query_lower:
        return None

    exact: dict[str, Any] | None = None
    partial: list[dict[str, Any]] = []
    for item in items:
        name = item.get("name", "").lower()
        if name == query_lower:
            if exact is None or edition_rank(item) > edition_rank(exact):
                exact = item
        elif query_lower in name or name in query_lower:
            partial.append(item)
    if exact is not None:
        return exact
    if not partial:
        return None

    def rank(item: dict[str, Any]) -> tuple[int, int]:
        name = item.get("name", "").lower()
        if query_lower in name:
            return (1, len(name))
        return (2, len(name))

    best = min(partial, key=rank)
    if rank(best)[0] >= 2:
        return None
    return best


def _lookup_by_slug(index: FiveToolsIndex, slug: str, store: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cleaned = short_slug(slug)
    matches: list[dict[str, Any]] = []
    seen: set[int] = set()

    def add(item: dict[str, Any] | None) -> None:
        if item is None:
            return
        marker = id(item)
        if marker in seen:
            return
        seen.add(marker)
        matches.append(item)

    if slug in store:
        add(store[slug])
    if cleaned in store:
        add(store[cleaned])
    for key, item in store.items():
        if key.startswith(f"{cleaned}__"):
            add(item)

    if not matches:
        raise FiveToolsNotFoundError(f"No entry found for '{slug}'.")

    return max(matches, key=edition_rank)


def _lookup_by_query(store_by_name: dict[str, dict[str, Any]], query: str, *, label: str) -> dict[str, Any]:
    exact = store_by_name.get(query.lower().strip())
    if exact is not None:
        return exact
    match = _pick_best_match(store_by_name.values(), query)
    if match is None:
        raise FiveToolsNotFoundError(f"No {label} found matching '{query}'.")
    return match


def normalize_spell(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    components = item.get("components")
    material = components.get("m") if isinstance(components, dict) else item.get("material")
    higher = render_entries(item.get("entriesHigherLevel"))
    return {
        **item,
        **_document_fields(item, slug=slug, kind="spell"),
        "slug": slug,
        "name": item["name"],
        "desc": render_entries(item.get("entries")),
        "level": format_spell_level(item.get("level")),
        "school": spell_school(item.get("school")),
        "casting_time": format_time(item.get("time")),
        "range": format_range(item.get("range")),
        "duration": format_duration(item.get("duration")),
        "components": format_components(components),
        "material": material,
        "higher_level": higher or None,
        "dnd_class": item.get("classes") or "—",
    }


def normalize_species(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    speed = item.get("speed") or {}
    walk = speed.get("walk") if isinstance(speed, dict) else None
    return {
        **item,
        **_document_fields(item, slug=slug, kind="species"),
        "slug": slug,
        "name": item["name"],
        "desc": render_entries(item.get("entries")),
        "size_raw": item.get("size") or "—",
        "speed": {"walk": walk} if walk is not None else {},
        "speed_desc": f"{walk} ft." if walk is not None else "—",
        "vision": render_entries(item.get("darkvision")),
        "traits": render_entries(item.get("entries")),
        "subraces": [],
    }


def _format_proficiencies(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for entry in value:
            if isinstance(entry, str):
                parts.append(entry.title())
            elif isinstance(entry, dict):
                if "choose" in entry:
                    choose = entry["choose"]
                    from_list = ", ".join(skill.replace("_", " ").title() for skill in choose.get("from", [])[:6])
                    count = choose.get("count", 1)
                    parts.append(f"Choose {count} from {from_list}")
                else:
                    for key, enabled in entry.items():
                        if enabled:
                            parts.append(key.title())
        return ", ".join(parts) if parts else "—"
    return str(value)


def _normalize_class_features(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for feature in sorted(features, key=lambda item: (item.get("level") or 0, item.get("name") or "")):
        name = str(feature.get("name") or "").strip()
        desc = render_entries(feature.get("entries"))
        if not name or not desc:
            continue
        if name.lower() in {"subclass feature", "subclass features"}:
            continue
        normalized.append({"level": feature.get("level") or 0, "name": name, "desc": desc})
    return normalized


def normalize_class(item: dict[str, Any], *, archetypes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    index = get_index()
    features = index.class_features(slug)
    feature_blurb = "\n\n".join(
        render_entries(feature.get("entries"))
        for feature in features
        if feature.get("level") == 1 and render_entries(feature.get("entries"))
    )[:1500]

    hd = item.get("hd") or {}
    prof = item.get("proficiency") or []
    starting = item.get("startingProficiencies") or {}
    primary = item.get("primaryAbility") or []

    spellcasting = None
    if item.get("spellcastingAbility"):
        spellcasting = str(item["spellcastingAbility"]).upper()
    elif primary:
        abilities = [next(iter(entry.keys())).upper() for entry in primary if isinstance(entry, dict)]
        if abilities:
            spellcasting = "/".join(abilities)

    normalized_archetypes = archetypes or []
    return {
        **item,
        **_document_fields(item, slug=slug, kind="class"),
        "slug": slug,
        "name": item["name"],
        "hit_dice": f"d{hd.get('faces', 8)}" if hd.get("faces") else "—",
        "hp_at_1st_level": f"{hd.get('faces', 8)} + CON" if hd.get("faces") else "—",
        "spellcasting_ability": spellcasting,
        "prof_saving_throws": ", ".join(str(score).upper() for score in prof) if prof else "—",
        "prof_skills": _format_proficiencies(starting.get("skills")),
        "prof_armor": _format_proficiencies(starting.get("armor") or starting.get("armorProficiencies")),
        "prof_weapons": _format_proficiencies(starting.get("weapons")),
        "desc": feature_blurb,
        "features": _normalize_class_features(features),
        "archetypes": normalized_archetypes,
    }


def normalize_background(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    skills = item.get("skillProficiencies")
    if isinstance(skills, list):
        skill_text = ", ".join(
            next(iter(entry.keys())).replace("_", " ").title()
            for entry in skills
            if isinstance(entry, dict) and entry
        )
    else:
        skill_text = skills

    return {
        **item,
        **_document_fields(item, slug=slug, kind="background"),
        "slug": slug,
        "name": item["name"],
        "desc": render_entries(item.get("entries")),
        "skill_proficiencies": skill_text or "—",
        "feature": item.get("feature") or None,
        "feature_desc": render_entries(item.get("entries")),
        "equipment": render_entries(item.get("startingEquipment")),
    }


def normalize_condition(item: dict[str, Any]) -> dict[str, Any] | None:
    desc = render_entries(item.get("entries"))
    if not desc:
        return None
    slug = item.get("slug") or slugify(item["name"])
    return {
        **item,
        **_document_fields(item, slug=slug, kind="condition"),
        "slug": slug,
        "name": item["name"],
        "desc": desc,
    }


def normalize_skill(item: dict[str, Any]) -> dict[str, Any] | None:
    desc = render_entries(item.get("entries"))
    if not desc:
        return None
    slug = item.get("slug") or slugify(item["name"]).replace("-", "_")
    return {
        **item,
        **_document_fields(item, slug=slug, kind="skill"),
        "slug": slug,
        "name": item["name"],
        "desc": desc,
        "ability": str(item.get("ability", "—")).upper(),
    }


def normalize_feat(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    return {
        **item,
        **_document_fields(item, slug=slug, kind="feat"),
        "slug": slug,
        "name": item["name"],
        "desc": render_entries(item.get("entries")),
    }


def normalize_weapon(item: dict[str, Any]) -> dict[str, Any]:
    index = get_index()
    slug = item.get("slug") or slugify(item["name"])
    props = item.get("property") or []
    prop_names = [index.property_name(str(code)) for code in props]
    category = f"{item.get('weaponCategory', '—').title()}" if item.get("weaponCategory") else "—"
    range_text = "Melee"
    if item.get("range"):
        range_text = f"{item['range']}/{item.get('longRange', item['range'])} ft."
    return {
        **item,
        **_document_fields(item, slug=slug, kind="weapon"),
        "slug": slug,
        "name": item["name"],
        "kind": "weapon",
        "category": category,
        "damage": item.get("dmg1") or "—",
        "damage_type": damage_type(item.get("dmgType")),
        "range": range_text,
        "properties": ", ".join(prop_names) if prop_names else "—",
    }


def normalize_armor(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    category = "Heavy" if item.get("heavy") else "Medium" if item.get("medium") else "Light"
    return {
        **item,
        **_document_fields(item, slug=slug, kind="armor"),
        "slug": slug,
        "name": item["name"],
        "kind": "armor",
        "ac": str(item.get("ac") or "—"),
        "category": category,
        "stealth_disadvantage": bool(item.get("stealth")),
        "strength_required": item.get("strength"),
    }


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    item_type = item.get("type") or "—"
    if isinstance(item_type, str) and "|" in item_type:
        item_type = item_type.split("|", 1)[0]
    return {
        **item,
        **_document_fields(item, slug=slug, kind="item"),
        "slug": slug,
        "name": item["name"],
        "kind": "item",
        "desc": render_entries(item.get("entries")),
        "category": item_type,
        "weight": format_weight(item.get("weight")),
        "cost": format_cost(item.get("value")),
    }


_SIZE_NAMES = {
    "T": "Tiny",
    "S": "Small",
    "M": "Medium",
    "L": "Large",
    "H": "Huge",
    "G": "Gargantuan",
}


def _format_monster_size(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_SIZE_NAMES.get(str(part), str(part)) for part in value) or "—"
    return _SIZE_NAMES.get(str(value), str(value or "—"))


def _format_monster_type(value: Any) -> str:
    if isinstance(value, str):
        return value.replace("_", " ").title()
    if isinstance(value, dict):
        base = str(value.get("type") or "—").replace("_", " ").title()
        tags = value.get("tags") or []
        if tags:
            return f"{base} ({', '.join(str(tag) for tag in tags)})"
        return base
    return "—"


def _monster_type_key(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, dict):
        return str(value.get("type") or "").lower()
    return ""


def _format_monster_ac(value: Any) -> str:
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            ac = first.get("ac") or first.get("special")
            from_text = first.get("from")
            if ac is not None and from_text:
                return f"{ac} ({', '.join(str(part) for part in from_text)})"
            return str(ac if ac is not None else "—")
        return str(first)
    return str(value or "—")


def _format_monster_hp(value: Any) -> str:
    if isinstance(value, dict):
        average = value.get("average")
        formula = value.get("formula")
        if average is not None and formula:
            return f"{average} ({formula})"
        return str(average or formula or "—")
    return str(value or "—")


def _format_monster_speed(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "—")
    parts: list[str] = []
    for key, amount in value.items():
        if key.startswith("can") or key == "choose":
            continue
        number = amount.get("number") if isinstance(amount, dict) else amount
        if number is None:
            continue
        if key == "walk":
            parts.append(f"{number} ft.")
        else:
            parts.append(f"{key.replace('_', ' ').title()} {number} ft.")
    return ", ".join(parts) or "—"


def _format_monster_cr(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("cr") or "—")
    return str(value or "—")


_ALIGNMENT_PARTS = {
    "L": "Lawful",
    "N": "Neutral",
    "NX": "Neutral",
    "NY": "Neutral",
    "C": "Chaotic",
    "G": "Good",
    "E": "Evil",
    "U": "Unaligned",
    "A": "Any Alignment",
}


def _format_alignment(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return _ALIGNMENT_PARTS.get(value.upper(), value).title()
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(part, str) for part in value):
            return " ".join(_ALIGNMENT_PARTS.get(part.upper(), part.title()) for part in value)
        if len(value) == 1:
            return _format_alignment(value[0])
    if isinstance(value, dict) and value.get("special"):
        return str(value["special"])
    return ""


def _format_damage_list(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        return format_damage_type_label(value.replace("_", " ").title())
    if isinstance(value, list):
        parts = [_format_damage_list(entry) for entry in value]
        return ", ".join(part for part in parts if part and part != "—") or "—"
    if isinstance(value, dict):
        if value.get("special"):
            return str(value["special"])
        nested = None
        for key in ("resist", "immune", "vulnerable", "conditionImmune"):
            if key in value:
                nested = _format_damage_list(value[key])
                break
        note = value.get("note")
        pre_note = value.get("preNote")
        if nested and nested != "—":
            prefix = f"{clean_tags(str(pre_note)).rstrip(': ')} " if pre_note else ""
            suffix = f" ({clean_tags(str(note)).strip('() ')})" if note else ""
            return f"{prefix}{nested}{suffix}".strip()
        if note or pre_note:
            return clean_tags(" ".join(str(part) for part in (pre_note, note) if part))
        return "—"
    return str(value)


def _format_ability_block(item: dict[str, Any]) -> str:
    def cell(key: str) -> str:
        score = item.get(key)
        if not isinstance(score, int):
            return f"{key.upper()}  —"
        modifier = (score - 10) // 2
        signed = f"+{modifier}" if modifier >= 0 else str(modifier)
        return f"{key.upper()} {score:>2} ({signed})"

    top = "  ".join(cell(key) for key in ("str", "dex", "con"))
    bottom = "  ".join(cell(key) for key in ("int", "wis", "cha"))
    return f"```\n{top}\n{bottom}\n```"


def _format_monster_senses(item: dict[str, Any]) -> str:
    parts: list[str] = []
    rendered = render_entries(item.get("senses"))
    if rendered:
        parts.append(rendered.replace("\n\n", ", "))
    passive = item.get("passive")
    if passive is not None:
        parts.append(f"Passive Perception {passive}")
    return ", ".join(parts) if parts else "—"


def _format_mapping(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "—"
    return ", ".join(f"{key.title()} {amount}" for key, amount in value.items())


def _format_spell_frequency(key: str) -> str:
    if key.endswith("e") and key[:-1].isdigit():
        return f"{key[:-1]}/day each"
    if key.isdigit():
        return f"{key}/day"
    return key.replace("_", " ").title()


def _render_spellcasting_block(block: dict[str, Any]) -> str:
    parts: list[str] = []
    header = render_entries(block.get("headerEntries"))
    name = block.get("name") or "Spellcasting"
    parts.append(f"**{name}.** {header}".strip() if header else f"**{name}.**")

    for key, label in (("will", "At Will"), ("constant", "Constant")):
        spells = block.get(key)
        if not spells:
            continue
        rendered = render_entries(spells).replace("\n", ", ")
        if rendered:
            parts.append(f"*{label}:* {rendered}")

    daily = block.get("daily")
    if isinstance(daily, dict):
        for frequency, spells in daily.items():
            rendered = render_entries(spells).replace("\n", ", ")
            if rendered:
                parts.append(f"*{_format_spell_frequency(frequency)}:* {rendered}")

    return "\n".join(parts)


def _render_named_blocks(blocks: Any) -> str:
    if not isinstance(blocks, list):
        return render_entries(blocks)
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "spellcasting":
            rendered = _render_spellcasting_block(block)
        else:
            rendered = render_entries(block)
        if rendered:
            parts.append(f"• {rendered.lstrip('• ')}")
    return "\n".join(parts)


def normalize_monster(item: dict[str, Any]) -> dict[str, Any]:
    slug = item.get("slug") or slugify(item["name"])
    size = _format_monster_size(item.get("size"))
    creature_type = _format_monster_type(item.get("type"))
    alignment = _format_alignment(item.get("alignment"))
    stat_bits = [f"{size} {creature_type}".strip()]
    if alignment:
        stat_bits.append(alignment)
    return {
        **item,
        **_document_fields(item, slug=slug, kind="monster"),
        "slug": slug,
        "name": item["name"],
        "size": size,
        "creature_type": creature_type,
        "creature_type_key": _monster_type_key(item.get("type")),
        "alignment": alignment,
        "ac": _format_monster_ac(item.get("ac")),
        "hp": _format_monster_hp(item.get("hp")),
        "speed": _format_monster_speed(item.get("speed")),
        "cr": _format_monster_cr(item.get("cr")),
        "abilities": _format_ability_block(item),
        "saves": _format_mapping(item.get("save")),
        "skills": _format_mapping(item.get("skill")),
        "senses": _format_monster_senses(item),
        "languages": ", ".join(str(part) for part in item.get("languages") or []) or "—",
        "vulnerable": _format_damage_list(item.get("vulnerable")),
        "resist": _format_damage_list(item.get("resist")),
        "immune": _format_damage_list(item.get("immune")),
        "condition_immune": _format_damage_list(item.get("conditionImmune")),
        "traits": _render_named_blocks(item.get("trait")),
        "actions": _render_named_blocks(item.get("action")),
        "bonus_actions": _render_named_blocks(item.get("bonus")),
        "reactions": _render_named_blocks(item.get("reaction")),
        "legendary": _render_named_blocks(item.get("legendary")),
        "spellcasting": _render_named_blocks(item.get("spellcasting")),
        "stat_line": ", ".join(stat_bits),
    }


def _register_glossary_item(item: dict[str, Any], endpoint: str) -> None:
    from srd.glossary import is_loaded, register_item

    if not is_loaded():
        return
    kind, _page = _GLOSSARY_PATHS.get(endpoint, ("item", "items"))
    register_item(
        name=item["name"],
        kind=kind,
        slug=item.get("slug", slugify(item["name"])),
        url=item.get("url") or entry_url_for_item(kind, item),
    )


_GLOSSARY_PATHS: dict[str, tuple[str, str]] = {
    "spells": ("spell", "spells"),
    "species": ("species", "races"),
    "classes": ("class", "classes"),
    "backgrounds": ("background", "backgrounds"),
    "conditions": ("condition", "conditionsdiseases"),
    "feats": ("feat", "feats"),
    "weapons": ("weapon", "items"),
    "armor": ("armor", "items"),
    "items": ("item", "items"),
    "monsters": ("monster", "bestiary"),
}


def register_glossary_item(item: dict[str, Any], endpoint: str) -> None:
    _register_glossary_item(item=item, endpoint=endpoint)


def _fetch(
    store_name: str,
    *,
    normalizer: Any,
    endpoint: str | None,
    label: str,
    slug: str | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    if slug:
        cached = _cache_get(label, slug)
        if cached is not None:
            return cached
    if query:
        cached = _cache_get(label, f"q:{query}")
        if cached is not None:
            return cached

    index = get_index()
    store: dict[str, dict[str, Any]] = getattr(index, store_name)
    if query is not None:
        raw = _lookup_by_query(store, query, label=label)
    else:
        raw = _lookup_by_slug(index, slug or "", store)
    item = normalizer(raw)
    if item is None:
        target = query if query is not None else slug
        raise FiveToolsNotFoundError(f"No {label} found for '{target}'.")
    if endpoint:
        _register_glossary_item(item, endpoint)
    item_slug = str(item.get("slug") or slug or "")
    if item_slug:
        _cache_put(label, item_slug, item)
    if query:
        _cache_put(label, f"q:{query}", item)
    return item


async def get_spell(slug: str) -> dict[str, Any]:
    return _fetch("spells_by_slug", slug=slug, normalizer=normalize_spell, endpoint="spells", label="spell")


async def search_spell(query: str) -> dict[str, Any]:
    return _fetch("spells_by_name", query=query, normalizer=normalize_spell, endpoint="spells", label="spell")


async def get_species(slug: str) -> dict[str, Any]:
    return _fetch("races_by_slug", slug=slug, normalizer=normalize_species, endpoint="species", label="species")


async def search_species(query: str) -> dict[str, Any]:
    return _fetch("races_by_name", query=query, normalizer=normalize_species, endpoint="species", label="species")


def _subclass_matches_class(subclass: dict[str, Any], char_class: dict[str, Any]) -> bool:
    parent_slug = char_class.get("slug") or slugify(char_class["name"])
    if subclass.get("class_slug") == parent_slug:
        return True
    return subclass.get("className") == char_class.get("name")


def _class_archetypes(char_class: dict[str, Any]) -> list[dict[str, Any]]:
    index = get_index()
    archetypes: list[dict[str, Any]] = []
    for subclass in index.subclasses:
        if not _subclass_matches_class(subclass, char_class):
            continue
        features = index.subclass_features(
            class_name=subclass.get("className", char_class["name"]),
            short_name=subclass.get("shortName") or subclass["name"],
        )
        level_three = next((feature for feature in features if feature.get("level") == 3), None)
        desc = render_entries(level_three.get("entries")) if level_three else ""
        subclass_source = _item_source(subclass)
        subclass_slug = subclass.get("slug") or slugify(subclass.get("shortName") or subclass["name"])
        archetypes.append(
            {
                "name": subclass["name"],
                "slug": subclass_slug,
                "desc": desc,
                "document__slug": subclass_source,
                "document__title": index.source_title(subclass_source),
            }
        )
    return archetypes


async def get_class(slug: str) -> dict[str, Any]:
    return _fetch(
        "classes_by_slug",
        slug=slug,
        normalizer=lambda raw: normalize_class(raw, archetypes=_class_archetypes(raw)),
        endpoint="classes",
        label="class",
    )


async def search_class(query: str) -> dict[str, Any]:
    return _fetch(
        "classes_by_name",
        query=query,
        normalizer=lambda raw: normalize_class(raw, archetypes=_class_archetypes(raw)),
        endpoint="classes",
        label="class",
    )


async def get_background(slug: str) -> dict[str, Any]:
    return _fetch(
        "backgrounds_by_slug",
        slug=slug,
        normalizer=normalize_background,
        endpoint="backgrounds",
        label="background",
    )


async def search_background(query: str) -> dict[str, Any]:
    return _fetch(
        "backgrounds_by_name",
        query=query,
        normalizer=normalize_background,
        endpoint="backgrounds",
        label="background",
    )


async def get_condition(slug: str) -> dict[str, Any]:
    return _fetch(
        "conditions_by_slug",
        slug=slug,
        normalizer=normalize_condition,
        endpoint="conditions",
        label="condition",
    )


async def search_condition(query: str) -> dict[str, Any]:
    return _fetch(
        "conditions_by_name",
        query=query,
        normalizer=normalize_condition,
        endpoint="conditions",
        label="condition",
    )


async def get_skill(slug: str) -> dict[str, Any]:
    return _fetch(
        "skills_by_slug",
        slug=slug.replace("-", "_"),
        normalizer=normalize_skill,
        endpoint=None,
        label="skill",
    )


async def get_feat(slug: str) -> dict[str, Any]:
    return _fetch("feats_by_slug", slug=slug, normalizer=normalize_feat, endpoint="feats", label="feat")


async def search_feat(query: str) -> dict[str, Any]:
    return _fetch("feats_by_name", query=query, normalizer=normalize_feat, endpoint="feats", label="feat")


async def get_weapon(slug: str) -> dict[str, Any]:
    return _fetch("weapons_by_slug", slug=slug, normalizer=normalize_weapon, endpoint="weapons", label="weapon")


async def search_weapon(query: str) -> dict[str, Any]:
    return _fetch("weapons_by_name", query=query, normalizer=normalize_weapon, endpoint="weapons", label="weapon")


async def get_armor(slug: str) -> dict[str, Any]:
    return _fetch("armor_by_slug", slug=slug, normalizer=normalize_armor, endpoint="armor", label="armor")


async def search_armor(query: str) -> dict[str, Any]:
    return _fetch("armor_by_name", query=query, normalizer=normalize_armor, endpoint="armor", label="armor")


async def get_item(slug: str) -> dict[str, Any]:
    return _fetch("items_by_slug", slug=slug, normalizer=normalize_item, endpoint="items", label="item")


async def search_item(query: str) -> dict[str, Any]:
    return _fetch("items_by_name", query=query, normalizer=normalize_item, endpoint="items", label="item")


async def get_monster(slug: str) -> dict[str, Any]:
    return _fetch("monsters_by_slug", slug=slug, normalizer=normalize_monster, endpoint="monsters", label="monster")


async def search_monster(query: str) -> dict[str, Any]:
    return _fetch("monsters_by_name", query=query, normalizer=normalize_monster, endpoint="monsters", label="monster")


def suggest_names(kind: str, query: str, *, limit: int = 25) -> list[str]:
    index = peek_index()
    if index is None:
        return []
    store_name = _KIND_NAME_STORES.get(kind)
    if not store_name:
        return []
    store: dict[str, dict[str, Any]] = getattr(index, store_name, {})
    needle = query.lower().strip()
    starts: list[str] = []
    contains: list[str] = []
    for name_key, item in store.items():
        name = str(item.get("name") or "")
        if not name:
            continue
        if not needle:
            starts.append(name)
        elif name_key.startswith(needle):
            starts.append(name)
        elif needle in name_key:
            contains.append(name)
        if len(starts) >= limit:
            break
    ordered: list[str] = []
    seen: set[str] = set()
    for name in starts + contains:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(name)
        if len(ordered) >= limit:
            break
    return ordered


async def search_equipment(query: str) -> dict[str, Any]:
    cleaned = query.strip()
    index = get_index()
    for store, endpoint, normalizer in (
        (index.weapons_by_name, "weapons", normalize_weapon),
        (index.armor_by_name, "armor", normalize_armor),
        (index.items_by_name, "items", normalize_item),
    ):
        exact = store.get(cleaned.lower())
        if exact is not None:
            normalized = normalizer(exact)
            normalized["kind"] = {"weapons": "weapon", "armor": "armor", "items": "item"}[endpoint]
            register_glossary_item(normalized, endpoint)
            return normalized

    last_error: FiveToolsError | None = None
    for search_fn in (search_weapon, search_armor, search_item):
        try:
            return await search_fn(query)
        except FiveToolsNotFoundError as exc:
            last_error = exc
    raise last_error or FiveToolsNotFoundError(f"No equipment found matching '{query}'.")


async def get_equipment(slug: str, *, kind: str | None = None) -> dict[str, Any]:
    if kind == "weapon":
        return await get_weapon(slug)
    if kind == "armor":
        return await get_armor(slug)
    if kind == "item":
        return await get_item(slug)

    for getter in (get_weapon, get_armor, get_item):
        try:
            return await getter(slug)
        except FiveToolsNotFoundError:
            continue
    raise FiveToolsNotFoundError(f"No equipment found for '{slug}'.")


def find_subclass(char_class: dict[str, Any], query: str) -> dict[str, Any] | None:
    query_lower = query.lower().strip()
    for archetype in char_class.get("archetypes", []):
        if archetype.get("name", "").lower() == query_lower:
            return archetype
    for archetype in char_class.get("archetypes", []):
        if query_lower in archetype.get("name", "").lower():
            return archetype
    return None


async def fetch_all(endpoint: str) -> list[dict[str, Any]]:
    index = await ensure_index_loaded()
    if endpoint == "spells":
        return list(index.spells_by_slug.values())
    if endpoint in {"species", "races"}:
        return list(index.races_by_slug.values())
    if endpoint == "classes":
        classes = list(index.classes_by_slug.values())
        subclasses = [
            {
                "name": subclass["name"],
                "source": subclass.get("source"),
                "key": api_key(
                    subclass.get("slug") or slugify(subclass["name"]),
                    _item_source(subclass),
                ),
                "slug": subclass.get("slug"),
                "subclass_of": {
                    "key": api_key(
                        subclass.get("class_slug", ""),
                        _item_source(subclass),
                    )
                },
            }
            for subclass in index.subclasses
        ]
        return classes + subclasses
    if endpoint == "backgrounds":
        return list(index.backgrounds_by_slug.values())
    if endpoint == "feats":
        return list(index.feats_by_slug.values())
    if endpoint == "conditions":
        return list(index.conditions_by_slug.values())
    if endpoint == "weapons":
        return list(index.weapons_by_slug.values())
    if endpoint == "armor":
        return list(index.armor_by_slug.values())
    if endpoint == "items":
        return list(index.items_by_slug.values())
    if endpoint in {"monsters", "bestiary"}:
        return list(index.monsters_by_slug.values())
    return []
