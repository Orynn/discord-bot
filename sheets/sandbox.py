from __future__ import annotations

from typing import Any

from combat.storage import clear_combat
from initiative.storage import clear_initiative
from players.discover import sandbox_player_id, sandbox_scope_id
from sheets.currency import Currency
from sheets.data import CharacterSheet
from sheets.equipment import ITEM_KIND_ARMOR, ITEM_KIND_ITEM, ITEM_KIND_WEAPON, Equipment
from sheets.spell_slots import SpellSlots
from sheets.storage import get_sheet, save_sheet

MOCK_NAME = "Mock"


def build_mock_sheet() -> CharacterSheet:
    """Ready-to-test Eldritch Knight: weapon, cantrip, heal, slots, gold."""
    equipment = Equipment()
    equipment.add_item(
        slug="longsword", name="Longsword", kind=ITEM_KIND_WEAPON, quantity=1
    )
    equipment.add_item(
        slug="chain-mail", name="Chain Mail", kind=ITEM_KIND_ARMOR, quantity=1
    )
    equipment.add_item(
        slug="shield", name="Shield", kind=ITEM_KIND_ARMOR, quantity=1
    )
    equipment.add_item(
        slug="explorers-pack",
        name="Explorer's Pack",
        kind=ITEM_KIND_ITEM,
        quantity=1,
    )
    return CharacterSheet(
        name=MOCK_NAME,
        species="Human",
        char_class="Fighter",
        subclass="Eldritch Knight",
        level=5,
        background="Soldier",
        abilities={
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 14,
            "wis": 10,
            "cha": 10,
        },
        hp_max=44,
        hp_current=44,
        ac=18,
        speed=30,
        save_proficiencies=["str", "con"],
        skill_proficiencies=["athletics", "perception", "intimidation"],
        spells=["fire-bolt", "shield", "cure-wounds", "magic-missile"],
        spell_slots=SpellSlots.from_dict(
            {"maximum": {"1": 3}, "current": {"1": 3}}
        ),
        currency=Currency(gp=50, sp=20),
        equipment=equipment,
        hit_dice_remaining=5,
        notes="Sandbox mock — isolated from player sheets. Use `;trash reset`.",
    )


def ensure_sandbox_sheet(*, guild_id: int, user_id: int) -> CharacterSheet:
    sheet = get_sheet(user_id=user_id, guild_id=guild_id)
    if sheet is not None:
        return sheet
    sheet = build_mock_sheet()
    save_sheet(user_id=user_id, guild_id=guild_id, sheet=sheet)
    return sheet


def reset_sandbox(*, guild_id: int, channel: Any) -> CharacterSheet:
    user_id = sandbox_player_id(channel)
    scope_id = sandbox_scope_id(channel)
    if user_id is None or scope_id is None:
        raise ValueError("Sandbox reset only works in #🚯trash.")
    sheet = build_mock_sheet()
    save_sheet(user_id=user_id, guild_id=guild_id, sheet=sheet)
    clear_combat(guild_id=guild_id, scope_id=scope_id)
    clear_initiative(guild_id=guild_id, scope_id=scope_id)
    return sheet
