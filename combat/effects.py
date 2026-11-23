"""Saving throws, conditions synced to sheets, and concentration."""

import random
from dataclasses import dataclass

from combat.encounter import Combatant, Encounter, condition_key
from sheets.data import CharacterSheet
from sheets.dice import ParsedDice, execute_roll
from sheets.storage import get_sheet, update_sheet

CONCENTRATION_DC_CAP = 30
# Conditions that make Strength and Dexterity saves fail automatically.
_AUTO_FAIL_STR_DEX = {"paralyzed", "stunned", "unconscious", "petrified"}
# Conditions that end concentration.
_BREAKS_CONCENTRATION = {
    "incapacitated",
    "paralyzed",
    "stunned",
    "unconscious",
    "petrified",
}


def set_player_condition(
    encounter: Encounter, combatant: Combatant, key: str, present: bool
) -> None:
    """Mirror a condition on the player's sheet, so `;roll` sees it too."""

    def updater(sheet: CharacterSheet) -> None:
        kept = [raw for raw in sheet.conditions if condition_key(raw) != key]
        if present:
            kept.append(key)
        sheet.conditions = kept

    if combatant.user_id is None:
        return
    try:
        update_sheet(
            user_id=combatant.user_id, guild_id=encounter.guild_id, updater=updater
        )
    except ValueError:
        pass


def player_has_condition(encounter: Encounter, combatant: Combatant, key: str) -> bool:
    if combatant.user_id is None:
        return False
    sheet = get_sheet(user_id=combatant.user_id, guild_id=encounter.guild_id)
    return sheet is not None and any(
        condition_key(raw) == key for raw in sheet.conditions
    )


def condition_keys(encounter: Encounter, combatant: Combatant) -> set[str]:
    keys = set(combatant.conditions)
    if combatant.is_player and combatant.user_id is not None:
        sheet = get_sheet(user_id=combatant.user_id, guild_id=encounter.guild_id)
        if sheet is not None:
            keys |= {condition_key(raw) for raw in sheet.conditions}
            if sheet.hp_max and sheet.hp_current <= 0:
                keys.add("unconscious")
    return keys


def add_condition(
    encounter: Encounter, combatant: Combatant, key: str, rounds: int | None
) -> None:
    encounter.set_condition(combatant, key, rounds)
    if combatant.is_player:
        set_player_condition(encounter, combatant, key, present=True)


def remove_condition(encounter: Encounter, combatant: Combatant, key: str) -> None:
    encounter.clear_condition(combatant, key)
    if combatant.is_player:
        set_player_condition(encounter, combatant, key, present=False)


# --- saving throws -----------------------------------------------------------


@dataclass
class SaveResult:
    combatant: Combatant
    total: int
    natural: int
    success: bool
    auto_fail: bool = False
    notes: tuple[str, ...] = ()

    def text(self, dc: int) -> str:
        if self.auto_fail:
            return "échec automatique"
        shown = (
            str(self.natural)
            if self.total == self.natural
            else f"{self.natural} → {self.total}"
        )
        icon = "✅" if self.success else "❌"
        extra = f" ({', '.join(self.notes)})" if self.notes else ""
        return f"{icon} {shown} vs DD {dc}{extra}"


def _natural(result) -> int:
    if result.d20_pair:
        return max(result.d20_pair) if result.advantage else min(result.d20_pair)
    return result.kept_rolls[0]


def roll_save(
    encounter: Encounter,
    combatant: Combatant,
    ability: str,
    dc: int,
    *,
    advantage: bool | None = None,
) -> SaveResult:
    keys = condition_keys(encounter, combatant)
    if ability in ("str", "dex") and keys & _AUTO_FAIL_STR_DEX:
        return SaveResult(combatant, 0, 0, False, auto_fail=True)
    if ability == "dex" and "restrained" in keys:
        advantage = None if advantage is True else False

    if combatant.is_player and combatant.user_id is not None:
        outcome: list = []

        def updater(sheet: CharacterSheet) -> None:
            # The sheet brings the save bonus, Bless, Lucky and inspiration.
            outcome.append(
                execute_roll(
                    dice=ParsedDice(count=1, sides=20, flat_modifier=0),
                    sheet=sheet,
                    modifier_tokens=[ability, "save"],
                    advantage=advantage,
                    dc=dc,
                )
            )

        try:
            update_sheet(
                user_id=combatant.user_id, guild_id=encounter.guild_id, updater=updater
            )
        except ValueError:
            outcome.clear()
        if outcome:
            result = outcome[0]
            notes = list(result.effect_notes)
            if result.lucky_used:
                notes.append("🍀 Chanceux")
            if result.spent_inspiration:
                notes.append("✨ inspiration")
            return SaveResult(
                combatant,
                result.total,
                _natural(result),
                result.total >= dc,
                notes=tuple(notes),
            )

    bonus = combatant.saves.get(ability, 0)
    faces = [random.randint(1, 20)]
    if advantage is not None:
        faces.append(random.randint(1, 20))
    natural = max(faces) if advantage else min(faces)
    total = natural + bonus
    notes = (
        ("⬆️ avantage",)
        if advantage
        else ("⬇️ désavantage",)
        if advantage is False
        else ()
    )
    return SaveResult(combatant, total, natural, total >= dc, notes=notes)


# --- concentration -----------------------------------------------------------


def start_concentration(
    encounter: Encounter, caster: Combatant, spell: str
) -> list[str]:
    lines = end_concentration(encounter, caster, reason="nouveau sort")
    caster.concentration = {"spell": spell, "links": []}
    return lines


def link_to_concentration(caster: Combatant, target: Combatant, key: str) -> None:
    if caster.concentration is not None:
        caster.concentration.setdefault("links", []).append([target.id, key])


def end_concentration(
    encounter: Encounter, caster: Combatant, *, reason: str = ""
) -> list[str]:
    if not caster.concentration:
        return []
    spell = caster.concentration.get("spell", "?")
    for target_id, key in caster.concentration.get("links", []):
        target = encounter.get(target_id)
        if target is not None:
            remove_condition(encounter, target, key)
    caster.concentration = None
    why = f" ({reason})" if reason else ""
    return [f"🧠 **{caster.name}** perd sa concentration sur {spell}{why}."]


def concentration_check(
    encounter: Encounter, combatant: Combatant, damage: int
) -> list[str]:
    """After damage: a Constitution save to keep concentrating."""
    if not combatant.concentration or damage <= 0:
        return []
    dc = min(CONCENTRATION_DC_CAP, max(10, damage // 2))
    result = roll_save(encounter, combatant, "con", dc)
    spell = combatant.concentration.get("spell", "?")
    if result.success:
        return [
            f"🧠 **{combatant.name}** garde sa concentration sur {spell} : {result.text(dc)}"
        ]
    return [
        f"🧠 Concentration de **{combatant.name}** : {result.text(dc)}"
    ] + end_concentration(encounter, combatant)


def concentration_breaks_on(key: str) -> bool:
    return key in _BREAKS_CONCENTRATION


def describe_concentration(combatant: Combatant) -> str:
    if not combatant.concentration:
        return ""
    return f"🧠 {combatant.concentration.get('spell', '?')}"
