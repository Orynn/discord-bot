from __future__ import annotations

from typing import Any

from combat.cards import (
    BUFF_BY_SLUG,
    DEFAULT_SPELL_RANGE_SQUARES,
    DODGE_CARD_ID,
    SCHOOL_EMOJI,
    WEAPON_CARD_ID,
    CardSnapshot,
    homebrew_card_id,
    is_healing_spell,
    parse_damage_roll,
    parse_aoe_radius,
    parse_range_squares,
    spell_card_id,
    spell_requires_concentration,
    spell_damage_roll,
    spell_save_ability,
    spell_save_half,
    spellcasting_ability,
    weapon_attack_ability,
)
from combat.monsters import MonsterProfile
from sheets.conditions import normalize_condition
from sheets.data import CharacterSheet, hit_die_sides
from sheets.equipment import ITEM_KIND_WEAPON
from srd import fivetools
from srd.fivetools_parser import (
    format_damage_type_label,
    spell_damage_type_label,
    spell_level_int,
)
from sheets.spell_view import is_homebrew_slug

NPC_WEAPON_COPIES = 4
NPC_DODGE_COPIES = 2
CANTRIP_COPIES = 3
LEVELED_SPELL_COPIES = 1
HOMEBREW_COPIES = 1

BUFF_EFFECT_TEXT: dict[str, str] = {
    "shield": "Negate the next hit against this creature.",
    "mage-armor": "Reduce each hit by 1d4.",
    "bless": "This creature's attacks deal +1d4.",
}


def _weapon_card(
    *,
    label: str,
    description: str,
    dice_count: int,
    dice_sides: int,
    flat_modifier: int = 0,
    ability: str | None,
    uses_proficiency: bool,
    damage_type_label: str | None = None,
    range_squares: int = 1,
) -> CardSnapshot:
    return CardSnapshot(
        card_id=WEAPON_CARD_ID,
        label=label,
        emoji="⚔️",
        description=description,
        needs_target=True,
        target_enemies_only=True,
        card_type="weapon",
        dice_count=dice_count,
        dice_sides=dice_sides,
        flat_modifier=flat_modifier,
        uses_proficiency=uses_proficiency,
        ability=ability,
        damage_type_label=damage_type_label,
        range_squares=range_squares,
    )


def _fallback_player_weapon(
    sheet: CharacterSheet, *, damage_type_label: str | None = None
) -> CardSnapshot:
    ability = weapon_attack_ability(sheet.char_class, sheet.abilities)
    die_sides = min(hit_die_sides(sheet.char_class), 12)
    description = (
        f"Unarmed/improvised: 1d{die_sides} + {ability.upper()} + proficiency."
    )
    if damage_type_label:
        description += f" Deals {damage_type_label} damage."
    return _weapon_card(
        label="Weapon Attack",
        description=description,
        dice_count=1,
        dice_sides=die_sides,
        ability=ability,
        uses_proficiency=True,
        damage_type_label=damage_type_label,
    )


def _claw_card() -> CardSnapshot:
    return _weapon_card(
        label="Claw",
        description="Natural attack: 1d6 damage.",
        dice_count=1,
        dice_sides=6,
        ability=None,
        uses_proficiency=False,
    )


def _monster_weapon_card(monster: MonsterProfile) -> CardSnapshot:
    dice = f"{monster.dice_count}d{monster.dice_sides}"
    if monster.flat_modifier:
        sign = "+" if monster.flat_modifier > 0 else ""
        dice = f"{dice}{sign}{monster.flat_modifier}"
    type_text = f" {monster.damage_type_label}" if monster.damage_type_label else ""
    return _weapon_card(
        label=monster.attack_name,
        description=f"{monster.attack_name}: {dice}{type_text} damage.",
        dice_count=monster.dice_count,
        dice_sides=monster.dice_sides,
        flat_modifier=monster.flat_modifier,
        ability=None,
        uses_proficiency=False,
        damage_type_label=monster.damage_type_label,
    )


def _dodge_card() -> CardSnapshot:
    return CardSnapshot(
        card_id=DODGE_CARD_ID,
        label="Dodge",
        emoji="🤸",
        description="Halve all damage until your next turn.",
        needs_target=False,
        card_type="dodge",
        ability="dex",
        buff="dodge",
        range_squares=0,
    )


def _spell_card(sheet: CharacterSheet, spell: dict[str, Any]) -> CardSnapshot | None:
    slug = spell.get("slug") or fivetools.short_slug(spell.get("key", ""))
    if not slug:
        return None

    level = spell_level_int(spell.get("level"))
    school = str(spell.get("school") or "—")
    emoji = SCHOOL_EMOJI.get(school.lower(), "✨")
    desc = str(spell.get("desc") or "")
    damage_roll = spell_damage_roll(spell)
    dice_count, dice_sides, flat_modifier = parse_damage_roll(damage_roll)
    damage_types = list(spell.get("damage_types") or spell.get("damageInflict") or [])
    healing = is_healing_spell(damage_types=damage_types, desc=desc)
    buff = BUFF_BY_SLUG.get(str(slug).lower())
    save_ability = spell_save_ability(spell)
    save_half = bool(save_ability and dice_count > 0 and spell_save_half(spell))
    inflicted = spell.get("conditionInflict") or spell.get("inflict_condition")
    inflict_condition = None
    if isinstance(inflicted, list) and inflicted:
        inflict_condition = normalize_condition(str(inflicted[0]))
    elif isinstance(inflicted, str):
        inflict_condition = normalize_condition(inflicted)
    target_allies = False
    target_enemies = False
    ability: str | None = None

    if healing:
        needs_target = True
        target_allies = True
        ability = spellcasting_ability(sheet.char_class) or "wis"
        effect = f"Restore {damage_roll or 'HP'} + {ability.upper()} (SRD)."
    elif save_ability:
        needs_target = True
        target_enemies = True
        ability = None
        type_label = (
            format_damage_type_label(str(damage_types[0]).replace("_", " ").title())
            if damage_types
            else None
        )
        type_text = f"{type_label} " if type_label else ""
        if dice_count > 0:
            outcome = "half on a success" if save_half else "nothing on a success"
            effect = (
                f"{save_ability.upper()} save · {damage_roll} {type_text}damage, {outcome}."
            ).replace("  ", " ")
        elif inflict_condition:
            effect = f"{save_ability.upper()} save or {inflict_condition}."
        else:
            effect = f"{save_ability.upper()} save (SRD)."
    elif dice_count > 0:
        needs_target = True
        target_enemies = True
        ability = spellcasting_ability(sheet.char_class) if level > 0 else None
        type_label = (
            format_damage_type_label(str(damage_types[0]).replace("_", " ").title())
            if damage_types
            else None
        )
        type_text = f"{type_label} " if type_label else ""
        mod_note = f" + {ability.upper()}" if ability and level > 0 else ""
        effect = f"Deal {damage_roll}{mod_note} {type_text}damage (SRD)."
    elif buff:
        needs_target = True
        target_allies = True
        effect = BUFF_EFFECT_TEXT[buff]
    else:
        needs_target = True
        effect = desc[:120] + ("…" if len(desc) > 120 else "")

    range_squares = parse_range_squares(spell.get("range"))
    if range_squares is None:
        range_squares = DEFAULT_SPELL_RANGE_SQUARES
    aoe_radius = parse_aoe_radius(spell)
    concentration = spell_requires_concentration(spell)
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
        buff=buff,
        save_ability=save_ability,
        save_half=save_half,
        inflict_condition=inflict_condition,
        range_squares=range_squares,
        aoe_radius=aoe_radius,
        concentration=concentration,
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
        range_squares=DEFAULT_SPELL_RANGE_SQUARES,
    )


async def _fetch_spell(slug: str) -> dict[str, Any] | None:
    if is_homebrew_slug(slug):
        return None
    try:
        return await fivetools.get_spell(slug=slug)
    except fivetools.Open5eError:
        return None


async def _lookup_equipped_weapon(sheet: CharacterSheet) -> dict[str, Any] | None:
    for item in sheet.equipment.equipped_items():
        if item.kind != ITEM_KIND_WEAPON:
            continue
        try:
            if item.slug:
                return await fivetools.get_weapon(slug=item.slug)
            return await fivetools.search_weapon(item.name)
        except fivetools.FiveToolsError:
            try:
                return await fivetools.search_weapon(item.name)
            except fivetools.FiveToolsError:
                continue
    return None


def _ability_for_weapon(sheet: CharacterSheet, weapon: dict[str, Any]) -> str:
    props = str(weapon.get("properties") or "").lower()
    range_text = str(weapon.get("range") or "Melee")
    if "finesse" in props:
        return (
            "dex"
            if sheet.abilities.get("dex", 10) >= sheet.abilities.get("str", 10)
            else "str"
        )
    if range_text.lower() != "melee":
        return "dex"
    return weapon_attack_ability(sheet.char_class, sheet.abilities)


async def _player_weapon_card(sheet: CharacterSheet) -> CardSnapshot:
    weapon = await _lookup_equipped_weapon(sheet)
    if weapon is None:
        return _fallback_player_weapon(sheet)
    count, sides, flat = parse_damage_roll(weapon.get("damage"))
    if count <= 0 or sides <= 0:
        type_label = weapon.get("damage_type")
        if type_label == "—":
            type_label = None
        return _fallback_player_weapon(sheet, damage_type_label=type_label)
    ability = _ability_for_weapon(sheet, weapon)
    type_label = weapon.get("damage_type")
    if type_label == "—":
        type_label = None
    dice = f"{count}d{sides}"
    if flat:
        dice = f"{dice}+{flat}"
    type_text = f" {type_label}" if type_label else ""
    name = str(weapon.get("name") or "Weapon")
    range_squares = parse_range_squares(weapon.get("range")) or 1
    return _weapon_card(
        label=name,
        description=f"{name}: {dice} + {ability.upper()} + proficiency{type_text}.",
        dice_count=count,
        dice_sides=sides,
        flat_modifier=flat,
        ability=ability,
        uses_proficiency=True,
        damage_type_label=type_label,
        range_squares=range_squares,
    )


async def build_combatant_deck(
    *,
    sheet: CharacterSheet | None,
    monster: MonsterProfile | None = None,
) -> tuple[list[str], dict[str, CardSnapshot]]:
    catalog: dict[str, CardSnapshot] = {}
    deck: list[str] = []

    if sheet is not None:
        weapon = await _player_weapon_card(sheet)
    elif monster is not None:
        weapon = _monster_weapon_card(monster)
    else:
        weapon = _claw_card()
    dodge = _dodge_card()
    catalog[weapon.card_id] = weapon
    catalog[dodge.card_id] = dodge
    deck.extend([weapon.card_id] * NPC_WEAPON_COPIES)
    dodge_copies = NPC_DODGE_COPIES
    if monster is not None and any(
        "nimble escape" in trait.lower() for trait in monster.traits
    ):
        dodge_copies += 1
    deck.extend([dodge.card_id] * dodge_copies)

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
