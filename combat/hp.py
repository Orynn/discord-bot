"""Damage, healing and death saves on combatants.

Player HP and death saves live on the character sheet; temporary HP and the
dead flag live on the combatant for the length of the fight.
"""

from combat.effects import concentration_check, end_concentration
from combat.encounter import Combatant, Encounter, apply_monster_hp, monster_state
from sheets.data import CharacterSheet
from sheets.dice import ParsedDice, execute_roll
from sheets.handlers import apply_hp
from sheets.storage import update_sheet

DEATH_SAVE_DC = 10


def _absorb_temp_hp(combatant: Combatant, amount: int) -> tuple[int, int]:
    """Temporary HP soak damage first. Returns (damage left, temp HP used)."""
    used = min(combatant.temp_hp, amount)
    combatant.temp_hp -= used
    return amount - used, used


def _update_player(
    encounter: Encounter, combatant: Combatant, updater
) -> CharacterSheet:
    if combatant.user_id is None:
        raise ValueError(f"**{combatant.name}** n’a pas de fiche.")
    try:
        return update_sheet(
            user_id=combatant.user_id, guild_id=encounter.guild_id, updater=updater
        )
    except ValueError as exc:
        if str(exc) == "Character sheet not found.":
            raise ValueError(f"**{combatant.name}** n’a plus de fiche.") from exc
        raise


def damage_combatant(
    encounter: Encounter, combatant: Combatant, amount: int, *, critical: bool = False
) -> list[str]:
    if combatant.dead:
        return [f"☠️ **{combatant.name}** est déjà mort."]
    amount, soaked = _absorb_temp_hp(combatant, max(0, amount))
    lines: list[str] = []
    if soaked:
        lines.append(
            f"🛡️ **{combatant.name}** : {soaked} absorbé(s) par les PV temporaires"
        )
    if amount == 0:
        return lines or [f"**{combatant.name}** ne subit aucun dégât."]

    if not combatant.is_player:
        previous, current = apply_monster_hp(combatant, -amount)
        lines.append(f"🗡️ **{combatant.name}** : −{amount} → {monster_state(combatant)}")
        if current == 0 and previous > 0:
            lines.append(f"💀 **{combatant.name}** est hors combat.")
            lines.extend(end_concentration(encounter, combatant, reason="hors combat"))
        else:
            lines.extend(concentration_check(encounter, combatant, amount))
        return lines

    state: dict[str, int | bool] = {}

    def updater(sheet: CharacterSheet) -> None:
        previous = sheet.hp_current
        state["previous"] = previous
        state["was_down"] = previous <= 0
        if previous <= 0:
            # Hit while down: one failed death save, two on a critical; a
            # stabilized creature starts its saves over.
            if sheet.death_save_successes >= 3:
                sheet.death_save_successes = 0
            sheet.death_save_failures += 2 if critical else 1
            state["massive"] = amount >= sheet.hp_max
            return
        sheet.hp_current = max(0, previous - amount)
        # Massive damage: what is left after reaching 0 HP is at least max HP.
        state["massive"] = sheet.hp_current == 0 and amount - previous >= sheet.hp_max

    sheet = _update_player(encounter, combatant, updater)
    if state["was_down"]:
        lines.append(
            f"🗡️ **{combatant.name}**, à terre, prend {amount} dégâts : "
            f"{'deux échecs' if critical else 'un échec'} au jet contre la mort "
            f"({min(sheet.death_save_failures, 3)}/3)."
        )
    else:
        lines.append(
            f"🗡️ **{combatant.name}** : PV {state['previous']} → "
            f"{sheet.hp_current}/{sheet.hp_max}"
        )
        if sheet.hp_current == 0:
            lines.append(
                f"🛌 **{combatant.name}** tombe à 0 PV : jets de sauvegarde contre la mort."
            )
    if state["massive"] or sheet.death_save_failures >= 3:
        combatant.dead = True
        reason = "dégâts massifs" if state["massive"] else "trois échecs"
        lines.append(f"☠️ **{combatant.name}** meurt ({reason}).")
    if sheet.hp_current == 0:
        lines.extend(end_concentration(encounter, combatant, reason="à 0 PV"))
    else:
        lines.extend(concentration_check(encounter, combatant, amount))
    return lines


def heal_combatant(
    encounter: Encounter, combatant: Combatant, amount: int
) -> list[str]:
    if combatant.dead:
        return [f"☠️ **{combatant.name}** est mort : il faut plus qu’un soin."]
    amount = max(0, amount)
    if not combatant.is_player:
        previous, current = apply_monster_hp(combatant, amount)
        line = f"💚 **{combatant.name}** : +{amount} → {monster_state(combatant)}"
        if previous == 0 and current > 0:
            line += " (de retour dans le combat)"
        return [line]

    before: list[int] = []

    def updater(sheet: CharacterSheet) -> None:
        before.append(sheet.hp_current)
        apply_hp(sheet, max(0, sheet.hp_current + amount))

    sheet = _update_player(encounter, combatant, updater)
    line = (
        f"💚 **{combatant.name}** : PV {before[0]} → {sheet.hp_current}/{sheet.hp_max}"
    )
    if before[0] == 0 and sheet.hp_current > 0:
        line += " — se relève !"
    return [line]


def set_temp_hp(combatant: Combatant, amount: int) -> str:
    # Temporary HP don't stack: keep the higher value.
    if amount <= combatant.temp_hp:
        return (
            f"**{combatant.name}** garde ses {combatant.temp_hp} PV temporaires "
            "(ils ne se cumulent pas)."
        )
    combatant.temp_hp = amount
    return f"🛡️ **{combatant.name}** : {amount} PV temporaires."


def roll_death_save(encounter: Encounter, combatant: Combatant) -> list[str]:
    if not combatant.is_player:
        raise ValueError("Les jets contre la mort sont pour les personnages joueurs.")
    if combatant.dead:
        raise ValueError(f"**{combatant.name}** est mort.")
    outcome: dict[str, object] = {}

    def updater(sheet: CharacterSheet) -> None:
        if sheet.hp_current > 0:
            raise ValueError("not_down")
        if sheet.death_save_successes >= 3:
            raise ValueError("stable")
        # A death save is a saving throw: Bless, Halfling Lucky and inspiration apply.
        result = execute_roll(
            dice=ParsedDice(count=1, sides=20, flat_modifier=0),
            sheet=sheet,
            modifier_tokens=[],
            advantage=None,
        )
        natural = (
            (max(result.d20_pair) if result.advantage else min(result.d20_pair))
            if result.d20_pair
            else result.kept_rolls[0]
        )
        outcome["total"] = result.total
        outcome["natural"] = natural
        outcome["notes"] = list(result.effect_notes) + (
            ["🍀 Chanceux"] if result.lucky_used else []
        )
        if natural == 20:
            apply_hp(sheet, 1)
            outcome["kind"] = "revive"
        elif natural == 1:
            sheet.death_save_failures += 2
            outcome["kind"] = "fumble"
        elif result.total >= DEATH_SAVE_DC:
            sheet.death_save_successes += 1
            outcome["kind"] = "success"
        else:
            sheet.death_save_failures += 1
            outcome["kind"] = "failure"

    try:
        sheet = _update_player(encounter, combatant, updater)
    except ValueError as exc:
        if str(exc) == "not_down":
            raise ValueError(f"**{combatant.name}** n’est pas à 0 PV.") from exc
        if str(exc) == "stable":
            raise ValueError(f"**{combatant.name}** est déjà stabilisé.") from exc
        raise

    total = outcome["total"]
    natural = outcome["natural"]
    shown = f"{natural}" if total == natural else f"{natural} → {total}"
    head = f"💀 Jet contre la mort de **{combatant.name}** : **{shown}**"
    notes = outcome["notes"]
    if notes:
        head += f" ({', '.join(str(note) for note in notes)})"
    successes = min(sheet.death_save_successes, 3)
    failures = min(sheet.death_save_failures, 3)
    tally = f"✅ {successes}/3 · ❌ {failures}/3"
    kind = outcome["kind"]
    if kind == "revive":
        return [
            head,
            f"🌟 20 naturel : **{combatant.name}** reprend 1 PV et se relève !",
        ]
    lines = [head]
    if kind == "fumble":
        lines.append(f"1 naturel : deux échecs. {tally}")
    elif kind == "success":
        lines.append(f"Réussite. {tally}")
    else:
        lines.append(f"Échec. {tally}")
    if sheet.death_save_failures >= 3:
        combatant.dead = True
        lines.append(f"☠️ **{combatant.name}** meurt.")
    elif sheet.death_save_successes >= 3:
        lines.append(f"🩹 **{combatant.name}** est stabilisé (inconscient, à 0 PV).")
    return lines
