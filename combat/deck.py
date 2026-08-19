from __future__ import annotations

from typing import Any

from combat.cards import (
    DODGE_CARD_ID,
    SCHOOL_EMOJI,
    WEAPON_CARD_ID,
    CardSnapshot,
    homebrew_card_id,
    is_healing_spell,
    parse_damage_roll,
    spell_card_id,
    spellcasting_ability,
    weapon_attack_ability,
)
from sheets.data import CharacterSheet, hit_die_sides
from sheets.equipment import ITEM_KIND_WEAPON
from srd import fivetools
from srd.fivetools_parser import format_damage_type_label, spell_damage_type_label, spell_level_int
from sheets.spell_view import is_homebrew_slug

NPC_WEAPON_COPIES = 4
NPC_DODGE_COPIES = 2
CANTRIP_COPIES = 3
LEVELED_SPELL_COPIES = 1
HOMEBREW_COPIES = 1


def _weapon_card(sheet: CharacterSheet | None, *, damage_type_label: str | None = None) -> CardSnapshot:
    if sheet is None:
        ability = "str"
        die_sides = 6
        uses_prof = False
        label = "Claw"
        description = "Natural attack: 1d6 damage."
    else:
        ability = weapon_attack_ability(sheet.char_class, sheet.abilities)
        die_sides = min(hit_die_sides(sheet.char_class), 12)
        uses_prof = True
        label = "Weapon Attack"
        ability_name = ability.upper()
        description = f"SRD weapon attack: 1d{die_sides} + {ability_name} + proficiency."
        if damage_type_label:
            description += f" Deals {damage_type_label} damage."

    return CardSnapshot(
        card_id=WEAPON_CARD_ID,
        label=label,
        emoji="⚔️",
        description=description,
        needs_target=True,
        target_enemies_only=True,
        card_type="weapon",
        dice_count=1,
        dice_sides=die_sides,
        uses_proficiency=uses_prof,
        ability=ability,
        damage_type_label=damage_type_label,
    )


def _dodge_card(sheet: CharacterSheet | None) -> CardSnapshot:
    ability = "dex"
    if sheet is not None:
        ability = weapon_attack_ability(sheet.char_class, sheet.abilities)
        if spellcasting_ability(sheet.char_class):
            ability = "dex"
    return CardSnapshot(
        card_id=DODGE_CARD_ID,
        label="Dodge",
        emoji="🤸",
        description="SRD Dodge: reduce the next damage you take (half, rounded down).",
        needs_target=False,
        card_type="dodge",
        ability="dex",
    )


def _spell_card(sheet: CharacterSheet, spell: dict[str, Any]) -> CardSnapshot | None:
    slug = spell.get("slug") or fivetools.short_slug(spell.get("key", ""))
    if not slug:
        return None

    level = spell_level_int(spell.get("level"))
    school = str(spell.get("school") or "—")
    emoji = SCHOOL_EMOJI.get(school.lower(), "✨")
    desc = str(spell.get("desc") or "")
    damage_roll = spell.get("damage_roll")
    dice_count, dice_sides, flat_modifier = parse_damage_roll(damage_roll)
    damage_types = list(spell.get("damage_types") or spell.get("damageInflict") or [])
    healing = is_healing_spell(damage_types=damage_types, desc=desc)

    if healing:
        needs_target = True
        target_allies = True
        target_enemies = False
        ability = spellcasting_ability(sheet.char_class) or "wis"
        effect = f"Restore {damage_roll or 'HP'} + {ability.upper()} (SRD)."
    elif dice_count > 0:
        needs_target = True
        target_allies = False
        target_enemies = True
        ability = spellcasting_ability(sheet.char_class) if level > 0 else None
        type_label = (
            format_damage_type_label(str(damage_types[0]).replace("_", " ").title()) if damage_types else None
        )
        type_text = f"{type_label} " if type_label else ""
        mod_note = f" + {ability.upper()}" if ability and level > 0 else ""
        effect = f"Deal {damage_roll}{mod_note} {type_text}damage (SRD)."
    else:
        needs_target = False
        target_allies = False
        target_enemies = False
        ability = None
        effect = desc[:120] + ("…" if len(desc) > 120 else "")

    level_label = "Cantrip" if level == 0 else f"Level {level}"
    return CardSnapshot(
        card_id=spell_card_id(slug),
        label=spell.get("name") or slug.replace("-", " ").title(),
        emoji=emoji,
        description=f"{level_label} · {effect}",
        needs_target=needs_target,
        target_allies_only=target_allies,
        target_enemies_only=target_enemies,
        card_type="spell",
        dice_count=dice_count,
        dice_sides=dice_sides,
        flat_modifier=flat_modifier,
        is_healing=healing,
        spell_level=level,
        spell_slug=slug,
        ability=ability,
        damage_type_label=spell_damage_type_label(spell),
    )


def _homebrew_card(name: str) -> CardSnapshot:
    card_id = homebrew_card_id(name)
    force_label = format_damage_type_label("Force")
    return CardSnapshot(
        card_id=card_id,
        label=name,
        emoji="📜",
        description=f"Homebrew spell: 1d8 {force_label} damage.",
        needs_target=True,
        target_enemies_only=True,
        card_type="homebrew",
        dice_count=1,
        dice_sides=8,
        damage_type_label=force_label,
    )


async def _fetch_spell(slug: str) -> dict[str, Any] | None:
    if is_homebrew_slug(slug):
        return None
    try:
        return await fivetools.get_spell(slug=slug)
    except fivetools.Open5eError:
        return None


async def _equipped_weapon_damage_type(sheet: CharacterSheet) -> str | None:
    for item in sheet.equipment.equipped_items():
        if item.kind != ITEM_KIND_WEAPON:
            continue
        try:
            if item.slug:
                weapon = await fivetools.get_weapon(slug=item.slug)
            else:
                weapon = await fivetools.search_weapon(item.name)
        except fivetools.FiveToolsError:
            continue
        damage_type = weapon.get("damage_type")
        if damage_type and damage_type != "—":
            return str(damage_type)
    return None


async def build_combatant_deck(
    *,
    sheet: CharacterSheet | None,
) -> tuple[list[str], dict[str, CardSnapshot]]:
    catalog: dict[str, CardSnapshot] = {}
    deck: list[str] = []

    weapon_type = await _equipped_weapon_damage_type(sheet) if sheet is not None else None
    weapon = _weapon_card(sheet, damage_type_label=weapon_type)
    dodge = _dodge_card(sheet)
    catalog[weapon.card_id] = weapon
    catalog[dodge.card_id] = dodge
    deck.extend([weapon.card_id] * NPC_WEAPON_COPIES)
    deck.extend([dodge.card_id] * NPC_DODGE_COPIES)

    if sheet is None:
        return deck, catalog

    for slug in sheet.spells:
        spell = await _fetch_spell(slug)
        if spell is None:
            continue
        card = _spell_card(sheet, spell)
        if card is None:
            continue
        catalog[card.card_id] = card
        copies = CANTRIP_COPIES if card.spell_level == 0 else LEVELED_SPELL_COPIES
        deck.extend([card.card_id] * copies)

    for name in sheet.homebrew_spells:
        card = _homebrew_card(name)
        catalog[card.card_id] = card
        deck.extend([card.card_id] * HOMEBREW_COPIES)

    return deck, catalog
