import random
from dataclasses import dataclass

from combat.cards import (
    BUFF_BY_SLUG,
    DODGE_CARD_ID,
    DRAW_PER_TURN,
    HAND_SIZE,
    MAX_LOG_LINES,
    WEAPON_CARD_ID,
    CardSnapshot,
    card_buff,
    card_label,
    card_makes_attack_roll,
    card_requires_target,
    is_spellbook_card,
    lookup_card,
    spellcasting_ability,
)
from combat.deck import build_combatant_deck
from combat.map import (
    apply_template,
    attack_targets_in_range,
    best_move_toward,
    cell_label,
    chebyshev,
    combatants_in_radius,
    distance_squares,
    ensure_positions,
    in_range,
    melee_targets,
    movement_blockers,
    occupies_cell,
    parse_cell,
    path_cells,
    path_length,
    place_new_combatant,
    remaining_squares,
    speed_for_sheet,
    targets_in_range,
    weapon_range_squares,
)
from combat.monsters import lookup_monster_profile
from combat.storage import (
    CombatState,
    CombatantState,
    clear_combat,
    get_combat,
    save_combat,
)
from combat.text import (
    already_acted,
    already_attacked,
    aoe_empty,
    cannot_attack_self,
    cannot_move,
    cannot_reach,
    combat_started,
    combatant_missing,
    concentration_held,
    concentration_lost,
    condition_fr,
    defeated,
    dies,
    drops_dying,
    dying_skip,
    ends_turn,
    monsters_win,
    moves_to,
    named_wins,
    no_survivors,
    not_enough_move,
    not_your_turn,
    opportunity,
    out_of_range,
    party_wins,
    skips_condition,
    skips_stable,
    stable,
    turn_passed,
)
from config import PREFIX
from players.discover import is_sandbox_owner_id
from initiative.storage import get_initiative
from sheets.conditions import (
    ATTACKER_DISADVANTAGE,
    DEFENDER_ADVANTAGE,
    sheet_condition_keys,
)
from sheets.data import CharacterSheet, ability_modifier
from sheets.dice import CRIT_FAIL_LABEL, CRIT_SUCCESS_LABEL
from sheets.storage import get_sheet, update_sheet

DEFAULT_NPC_HP = 20
DEFAULT_NPC_AC = 10
DEFAULT_NPC_ATTACK_BONUS = 4
DEFAULT_NPC_SAVE_DC = 13
SKIP_TURN_CONDITIONS = frozenset(
    {"paralyzed", "stunned", "unconscious", "incapacitated"}
)


@dataclass(frozen=True)
class PlayResult:
    message: str
    combat_over: bool = False
    winner: str | None = None


def _sheet_for(combatant: CombatantState, *, guild_id: int) -> CharacterSheet | None:
    if combatant.user_id is None:
        return None
    return get_sheet(user_id=combatant.user_id, guild_id=guild_id)


def _side(combatant: CombatantState) -> str:
    return "npc" if combatant.user_id is None else "pc"


def _same_side(actor: CombatantState, other: CombatantState) -> bool:
    return _side(actor) == _side(other)


def _is_self_target(actor: CombatantState, other: CombatantState) -> bool:
    return other is actor or other.name.lower() == actor.name.lower()


def _hostile_card(card: CardSnapshot) -> bool:
    if card.target_allies_only or card.is_healing:
        return False
    return True


def can_control_combatant(
    *,
    combatant: CombatantState,
    user_id: int,
    is_admin: bool,
    scope_id: int | None = None,
) -> bool:
    if is_sandbox_owner_id(combatant.user_id):
        return True
    if combatant.user_id is None:
        if is_admin:
            return True
        return scope_id is not None and int(user_id) == int(scope_id)
    return int(user_id) == int(combatant.user_id)


def _ability_mod(
    combatant: CombatantState, ability: str | None, *, guild_id: int
) -> int:
    if not ability:
        return 0
    sheet = _sheet_for(combatant, guild_id=guild_id)
    if sheet is None:
        return 0
    return ability_modifier(sheet.abilities[ability])


def _prof_bonus(combatant: CombatantState, *, guild_id: int) -> int:
    sheet = _sheet_for(combatant, guild_id=guild_id)
    if sheet is None:
        return 0
    return sheet.get_prof_bonus()


def _roll_dice(count: int, sides: int) -> tuple[int, list[int]]:
    if count <= 0 or sides <= 0:
        return 0, []
    rolls = [random.randint(1, sides) for _ in range(count)]
    return sum(rolls), rolls


def _effect_buff(combatant: CombatantState, effect_id: str) -> str | None:
    card = lookup_card(combatant.card_catalog, effect_id)
    if card is not None:
        return card_buff(card)
    if effect_id == DODGE_CARD_ID:
        return "dodge"
    if effect_id.startswith("spell:"):
        return BUFF_BY_SLUG.get(effect_id.split(":", 1)[1])
    return None


def _buff_effect_id(combatant: CombatantState, buff: str) -> str | None:
    for effect_id in combatant.effects:
        if _effect_buff(combatant, effect_id) == buff:
            return effect_id
    return None


def _has_buff(combatant: CombatantState, buff: str) -> bool:
    return _buff_effect_id(combatant, buff) is not None


def _consume_buff(combatant: CombatantState, buff: str) -> bool:
    effect_id = _buff_effect_id(combatant, buff)
    if effect_id is None:
        return False
    combatant.effects.remove(effect_id)
    return True


def _drop_concentration(
    state: CombatState, combatant: CombatantState, *, reason: str
) -> None:
    effect_id = combatant.concentrating
    if not effect_id:
        return
    combatant.concentrating = ""
    for other in state.combatants.values():
        if effect_id in other.effects:
            other.effects.remove(effect_id)
    _append_log(state, concentration_lost(combatant.name, reason))


def _begin_concentration(
    state: CombatState, actor: CombatantState, card: CardSnapshot
) -> None:
    if not card.concentration:
        return
    if actor.concentrating:
        _drop_concentration(state, actor, reason="nouveau sort")
    actor.concentrating = card.card_id


def _concentration_check(
    state: CombatState, combatant: CombatantState, damage: int
) -> None:
    if not combatant.concentrating or damage <= 0:
        return
    dc = max(10, damage // 2)
    modifier = _save_modifier(combatant, "con", guild_id=state.guild_id)
    roll, roll_note = _roll_d20(None)
    total = roll + modifier
    if roll == 1:
        success = False
    elif roll == 20:
        success = True
    else:
        success = total >= dc
    bonus = f"{modifier:+d}" if modifier else "+0"
    if success:
        _append_log(
            state,
            f"{concentration_held(combatant.name)} "
            f"(CON {roll_note}{bonus} vs DD {dc})",
        )
        return
    _drop_concentration(
        state,
        combatant,
        reason=f"CON {roll_note}{bonus} vs DD {dc}",
    )


def _has_named_trait(combatant: CombatantState, needle: str) -> bool:
    return any(needle in trait.lower() for trait in combatant.traits)


def _living_ally(state: CombatState, actor: CombatantState) -> bool:
    return any(
        combatant is not actor and combatant.hp > 0 and _same_side(actor, combatant)
        for combatant in state.combatants.values()
    )


def _is_eliminated(combatant: CombatantState) -> bool:
    if combatant.user_id is None:
        return combatant.hp <= 0
    return combatant.death_save_failures >= 3


def _in_fight(combatant: CombatantState) -> bool:
    return not _is_eliminated(combatant)


def _condition_keys(combatant: CombatantState, *, guild_id: int) -> set[str]:
    keys: set[str] = set()
    sheet = _sheet_for(combatant, guild_id=guild_id)
    if sheet is not None:
        keys |= sheet_condition_keys(sheet)
    for raw in combatant.conditions:
        keys.add(str(raw).lower())
    if (
        combatant.user_id is not None
        and combatant.hp <= 0
        and not _is_eliminated(combatant)
    ):
        keys.add("unconscious")
    return keys


def _spell_save_dc(actor: CombatantState, *, guild_id: int) -> int:
    sheet = _sheet_for(actor, guild_id=guild_id)
    if sheet is None:
        return DEFAULT_NPC_SAVE_DC
    ability = spellcasting_ability(sheet.char_class)
    return 8 + sheet.get_prof_bonus() + _ability_mod(actor, ability, guild_id=guild_id)


def _save_modifier(combatant: CombatantState, ability: str, *, guild_id: int) -> int:
    sheet = _sheet_for(combatant, guild_id=guild_id)
    if sheet is None:
        return 0
    return sheet.get_save_modifier(ability)


def _apply_condition(state: CombatState, target: CombatantState, condition: str) -> str:
    key = condition.lower().strip()
    if key not in target.conditions:
        target.conditions.append(key)
    if target.user_id is not None:

        def _add(sheet: CharacterSheet) -> None:
            if key not in sheet.conditions:
                sheet.conditions.append(key)

        update_sheet(user_id=target.user_id, guild_id=state.guild_id, updater=_add)
    return f" — {condition_fr(key)}"


def _combatant_ac(combatant: CombatantState, *, guild_id: int) -> int:
    sheet = _sheet_for(combatant, guild_id=guild_id)
    if sheet is not None:
        return int(sheet.ac or 10)
    return int(combatant.ac or DEFAULT_NPC_AC)


def _attack_bonus(actor: CombatantState, card: CardSnapshot, *, guild_id: int) -> int:
    if actor.user_id is None:
        return int(actor.attack_bonus)
    ability = card.ability
    if ability is None and card.card_type in {"spell", "homebrew"}:
        sheet = _sheet_for(actor, guild_id=guild_id)
        if sheet is not None:
            ability = spellcasting_ability(sheet.char_class)
    ability_mod = _ability_mod(actor, ability, guild_id=guild_id)
    uses_prof = card.uses_proficiency or card.card_type in {"spell", "homebrew"}
    prof = _prof_bonus(actor, guild_id=guild_id) if uses_prof else 0
    return ability_mod + prof


def _ranged_melee_disadvantage(
    state: CombatState, actor: CombatantState, card: CardSnapshot
) -> bool:
    if card.card_type != "weapon":
        return False
    if card.range_squares is None or card.range_squares <= 1:
        return False
    return bool(melee_targets(state, actor))


def _attack_advantage(
    state: CombatState,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
    *,
    guild_id: int,
) -> bool | None:
    actor_keys = _condition_keys(actor, guild_id=guild_id)
    target_keys = _condition_keys(target, guild_id=guild_id)
    disadv = bool(actor_keys & ATTACKER_DISADVANTAGE)
    adv = bool(target_keys & DEFENDER_ADVANTAGE)
    if _ranged_melee_disadvantage(state, actor, card):
        disadv = True
    if _pack_tactics_advantage(state, actor, target):
        adv = True
    if adv and disadv:
        return None
    if adv:
        return True
    if disadv:
        return False
    return None


def _pack_tactics_advantage(
    state: CombatState, actor: CombatantState, target: CombatantState
) -> bool:
    if not _has_named_trait(actor, "pack tactics"):
        return False
    return any(
        other is not actor
        and other is not target
        and occupies_cell(other)
        and _same_side(actor, other)
        and distance_squares(other, target) == 1
        for other in state.combatants.values()
    )


def _roll_d20(advantage: bool | None) -> tuple[int, str]:
    if advantage is None:
        roll = random.randint(1, 20)
        return roll, str(roll)
    first = random.randint(1, 20)
    second = random.randint(1, 20)
    chosen = max(first, second) if advantage else min(first, second)
    tag = "av" if advantage else "désav"
    return chosen, f"{chosen} ({first}/{second} {tag})"


def _resolve_attack_roll(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> tuple[bool, bool, str]:
    bonus = _attack_bonus(actor, card, guild_id=state.guild_id)
    ac = _combatant_ac(target, guild_id=state.guild_id)
    advantage = _attack_advantage(
        state, actor, target, card, guild_id=state.guild_id
    )
    roll, roll_note = _roll_d20(advantage)
    total = roll + bonus
    bonus_note = f"{bonus:+d}" if bonus else "+0"
    if roll == 1:
        return (
            False,
            False,
            f"{CRIT_FAIL_LABEL} {roll_note}{bonus_note} vs CA {ac} — raté",
        )
    if roll == 20:
        return (
            True,
            True,
            f"{CRIT_SUCCESS_LABEL} {roll_note}{bonus_note} vs CA {ac} — touché",
        )
    hit = total >= ac
    verb = "touché" if hit else "raté"
    return hit, False, f"{roll_note}{bonus_note} vs CA {ac} — {verb}"


def _expire_turn_start_effects(combatant: CombatantState) -> None:
    while DODGE_CARD_ID in combatant.effects:
        combatant.effects.remove(DODGE_CARD_ID)


def _append_log(state: CombatState, line: str) -> None:
    state.log.append(line)
    if len(state.log) > MAX_LOG_LINES:
        state.log = state.log[-MAX_LOG_LINES:]


def _reshuffle_discard(combatant: CombatantState) -> None:
    if combatant.deck or not combatant.discard:
        return
    combatant.deck.extend(combatant.discard)
    combatant.discard.clear()
    random.shuffle(combatant.deck)


def _discard_card(combatant: CombatantState, card_id: str) -> None:
    combatant.discard.append(card_id)


def _shuffle_and_deal(combatant: CombatantState) -> None:
    random.shuffle(combatant.deck)
    while len(combatant.hand) < HAND_SIZE:
        drawn = _draw_card(combatant)
        if drawn is None:
            break


def _draw_card(combatant: CombatantState) -> str | None:
    _reshuffle_discard(combatant)
    if not combatant.deck:
        return None
    card_id = combatant.deck.pop()
    combatant.hand.append(card_id)
    return card_id


def _restore_sheet_hp(sheet: CharacterSheet) -> None:
    if sheet.hp_max:
        sheet.hp_current = sheet.hp_max
    sheet.reset_death_saves()


def apply_hp_to_live_combat(
    *,
    guild_id: int,
    scope_id: int,
    user_id: int,
    hp: int,
    max_hp: int | None = None,
) -> str | None:
    """Mirror a sheet HP change onto that player's combatant, if any."""
    state = get_combat(guild_id=guild_id, scope_id=scope_id)
    if state is None:
        return None
    combatant = next(
        (entry for entry in state.combatants.values() if entry.user_id == user_id),
        None,
    )
    if combatant is None:
        return None
    combatant.hp = hp
    if max_hp is not None and max_hp > 0:
        combatant.max_hp = max_hp
    if combatant.hp > 0:
        combatant.death_save_successes = 0
        combatant.death_save_failures = 0
    save_combat(state)
    return combatant.name


def _sync_hp_to_sheet(combatant: CombatantState, *, guild_id: int) -> None:
    if combatant.user_id is None:
        return
    if get_sheet(user_id=combatant.user_id, guild_id=guild_id) is None:
        return

    def _apply(sheet: CharacterSheet) -> None:
        sheet.hp_current = combatant.hp
        if combatant.hp > 0:
            sheet.reset_death_saves()
            combatant.death_save_successes = 0
            combatant.death_save_failures = 0
        else:
            sheet.death_save_successes = combatant.death_save_successes
            sheet.death_save_failures = combatant.death_save_failures

    update_sheet(user_id=combatant.user_id, guild_id=guild_id, updater=_apply)


def _living_of(state: CombatState, side: str) -> list[CombatantState]:
    return [
        combatant
        for combatant in state.combatants.values()
        if combatant.hp > 0 and _side(combatant) == side
    ]


def _has_side(state: CombatState, side: str) -> bool:
    return any(_side(combatant) == side for combatant in state.combatants.values())


def _check_victory(state: CombatState) -> PlayResult | None:
    if not _has_side(state, "pc") or not _has_side(state, "npc"):
        return None
    living_pcs = _living_of(state, "pc")
    living_npcs = _living_of(state, "npc")
    if not living_pcs and not living_npcs:
        _append_log(state, no_survivors())
        return PlayResult(message=no_survivors(), combat_over=True)
    if living_npcs and living_pcs:
        return None
    if not living_npcs:
        if len(living_pcs) == 1:
            winner = living_pcs[0].name
            message = named_wins(winner)
        else:
            winner = "the party"
            message = party_wins()
    elif len(living_npcs) == 1:
        winner = living_npcs[0].name
        message = named_wins(winner)
    else:
        winner = "the monsters"
        message = monsters_win()
    _append_log(state, message.rstrip("!") + " !")
    return PlayResult(message=message, combat_over=True, winner=winner)


def conclude_if_over(state: CombatState) -> PlayResult | None:
    victory = _check_victory(state)
    if victory is None:
        return None
    clear_combat(guild_id=state.guild_id, scope_id=state.scope_id)
    return victory


def _finish_action(state: CombatState, message: str) -> PlayResult:
    victory = conclude_if_over(state)
    if victory is None:
        save_combat(state)
        return PlayResult(message=message)
    text = f"{message}\n{victory.message}" if message else victory.message
    return PlayResult(message=text, combat_over=True, winner=victory.winner)


def _remove_from_turn_order(state: CombatState, combatant_key: str) -> None:
    combatant = state.combatants.get(combatant_key)
    if combatant is None:
        return
    name = combatant.name
    if name not in state.turn_order:
        return
    removed_index = state.turn_order.index(name)
    state.turn_order = [entry for entry in state.turn_order if entry != name]
    if not state.turn_order:
        state.active_index = 0
        return
    if removed_index < state.active_index:
        state.active_index -= 1
    state.active_index %= len(state.turn_order)


def _format_dice_note(*, rolls: list[int], modifier: int) -> str:
    if not rolls:
        return str(modifier) if modifier else "0"
    dice_label = "+".join(str(value) for value in rolls)
    if modifier:
        sign = "+" if modifier >= 0 else ""
        return f"{dice_label}{sign}{modifier}"
    return dice_label


def _apply_damage(
    state: CombatState,
    *,
    source: CombatantState,
    target: CombatantState,
    amount: int,
    action_label: str,
    damage_type_label: str | None = None,
) -> str:
    notes: list[str] = []
    was_up = target.hp > 0
    was_stable = (
        target.user_id is not None
        and target.hp <= 0
        and target.death_save_successes >= 3
        and target.death_save_failures < 3
    )
    if _consume_buff(target, "shield"):
        amount = 0
        notes.append("Bouclier : annulé")
    else:
        if DODGE_CARD_ID in target.effects:
            amount = amount // 2
            notes.append("Esquive : moitié")
        if _has_buff(target, "mage-armor"):
            reduction, _ = _roll_dice(1, 4)
            amount = max(0, amount - reduction)
            notes.append(f"Armure du mage -{reduction}")

    target.hp = max(0, target.hp - amount)
    extra_save = False
    if target.user_id is not None and target.hp <= 0 and amount > 0:
        if was_up:
            target.death_save_successes = 0
            target.death_save_failures = 0
        elif was_stable:
            target.death_save_successes = 0
            target.death_save_failures = 1
            extra_save = True
        else:
            target.death_save_failures += 1
            extra_save = True

    _sync_hp_to_sheet(target, guild_id=state.guild_id)
    type_part = f" {damage_type_label}" if damage_type_label else ""
    note = f" ({'; '.join(notes)})" if notes else ""
    line = (
        f"**{source.name}** attaque **{target.name}** avec **{action_label}** "
        f"— **{amount}**{type_part} dégâts{note}"
        f"{_hp_suffix(target)}"
    )
    _append_log(state, line)
    if amount > 0:
        _concentration_check(state, target, amount)

    if target.user_id is None:
        if target.hp <= 0:
            _append_log(state, defeated(target.name))
            _remove_from_turn_order(state, target.name.lower())
    elif target.hp <= 0:
        if extra_save:
            _append_log(
                state,
                f"**{target.name}** subit un échec de jet de mort "
                f"({target.death_save_successes}R/{target.death_save_failures}E).",
            )
        else:
            _append_log(state, drops_dying(target.name))
        if target.death_save_failures >= 3:
            _append_log(state, dies(target.name))
            _remove_from_turn_order(state, target.name.lower())

    return line


def _resolve_damage_card(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> str:
    attack_note = ""
    crit = False
    if card_makes_attack_roll(card):
        hit, crit, attack_note = _resolve_attack_roll(
            state, actor=actor, target=target, card=card
        )
        if not hit:
            line = (
                f"**{actor.name}** attaque **{target.name}** avec **{card.label}** "
                f"— raté ({attack_note})"
            )
            _append_log(state, line)
            return line

    dice_count = card.dice_count * 2 if crit else card.dice_count
    dice_total, dice_rolls = _roll_dice(dice_count, card.dice_sides)
    ability_mod = _ability_mod(actor, card.ability, guild_id=state.guild_id)
    prof = _prof_bonus(actor, guild_id=state.guild_id) if card.uses_proficiency else 0
    total = dice_total + ability_mod + prof + card.flat_modifier
    extra_notes: list[str] = []
    if attack_note:
        extra_notes.append(attack_note)
    if crit:
        extra_notes.append("crit")
    if _has_buff(actor, "bless"):
        bless_total, bless_rolls = _roll_dice(1, 4)
        total += bless_total
        extra_notes.append(f"Bless {bless_total}")
    if _has_named_trait(actor, "pack tactics") and _living_ally(state, actor):
        total += 2
        extra_notes.append("Pack Tactics +2")
    mod_parts = []
    if ability_mod:
        mod_parts.append(
            f"{card.ability.upper()} {ability_mod:+d}"
            if card.ability
            else str(ability_mod)
        )
    if prof:
        mod_parts.append(f"prof +{prof}")
    if card.flat_modifier:
        mod_parts.append(str(card.flat_modifier))
    mod_note = f" ({', '.join(mod_parts)})" if mod_parts else ""
    extra = f" ({', '.join(extra_notes)})" if extra_notes else ""
    action_label = (
        f"{card.label} [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + prof + card.flat_modifier)}]"
        f"{mod_note}{extra}"
    )
    return _apply_damage(
        state,
        source=actor,
        target=target,
        amount=total,
        action_label=action_label,
        damage_type_label=card.damage_type_label,
    )


def _resolve_save_card(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> str:
    ability = card.save_ability or "dex"
    dc = _spell_save_dc(actor, guild_id=state.guild_id)
    modifier = _save_modifier(target, ability, guild_id=state.guild_id)
    roll, roll_note = _roll_d20(None)
    total = roll + modifier
    if roll == 1:
        success = False
    elif roll == 20:
        success = True
    else:
        success = total >= dc
    bonus_note = f"{modifier:+d}" if modifier else "+0"
    outcome = "réussite" if success else "échec"
    save_note = f"{ability.upper()} {roll_note}{bonus_note} vs DD {dc} — {outcome}"

    if card.dice_count > 0:
        dice_total, dice_rolls = _roll_dice(card.dice_count, card.dice_sides)
        ability_mod = _ability_mod(actor, card.ability, guild_id=state.guild_id)
        amount = dice_total + ability_mod + card.flat_modifier
        extra_notes = [save_note]
        if _has_buff(actor, "bless"):
            bless_total, _bless_rolls = _roll_dice(1, 4)
            amount += bless_total
            extra_notes.append(f"Bless {bless_total}")
        if success and card.save_half:
            amount = amount // 2
            extra_notes.append("moitié")
        elif success:
            amount = 0
            extra_notes.append("aucun dégât")
        extra = f" ({', '.join(extra_notes)})"
        action_label = (
            f"{card.label} [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + card.flat_modifier)}]"
            f"{extra}"
        )
        line = _apply_damage(
            state,
            source=actor,
            target=target,
            amount=amount,
            action_label=action_label,
            damage_type_label=card.damage_type_label,
        )
        if not success and card.inflict_condition:
            extra_cond = _apply_condition(state, target, card.inflict_condition)
            line = f"{line}{extra_cond}"
            _append_log(
                state,
                f"**{target.name}** est {condition_fr(card.inflict_condition)}.",
            )
        return line

    if success:
        line = f"**{target.name}** résiste à **{card.label}** ({save_note})"
        _append_log(state, line)
        return line

    extra = ""
    if card.inflict_condition:
        extra = _apply_condition(state, target, card.inflict_condition)
    line = (
        f"**{actor.name}** lance **{card.label}** sur **{target.name}** "
        f"— {save_note}{extra}"
    )
    _append_log(state, line)
    return line


def _resolve_aoe_card(
    state: CombatState,
    *,
    actor: CombatantState,
    card: CardSnapshot,
    center: tuple[int, int],
) -> str:
    victims = [
        combatant
        for combatant in combatants_in_radius(
            state, center[0], center[1], card.aoe_radius or 0
        )
        if combatant is not actor
    ]
    cell = cell_label(center[0], center[1], state)
    if not victims:
        line = aoe_empty(actor.name, card.label, cell)
        _append_log(state, line)
        return line
    parts = [f"**{actor.name}** lance **{card.label}** sur **{cell}**."]
    for victim in victims:
        if card.save_ability:
            parts.append(
                _resolve_save_card(state, actor=actor, target=victim, card=card)
            )
        elif card.is_healing:
            parts.append(
                _resolve_heal_card(state, actor=actor, target=victim, card=card)
            )
        elif card.dice_count > 0:
            parts.append(
                _resolve_damage_card(state, actor=actor, target=victim, card=card)
            )
        else:
            if card.card_id not in victim.effects:
                victim.effects.append(card.card_id)
            parts.append(f"**{victim.name}** est touché par **{card.label}**.")
    return "\n".join(parts)


def _resolve_heal_card(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> str:
    dice_total, dice_rolls = _roll_dice(card.dice_count, card.dice_sides)
    ability_mod = _ability_mod(actor, card.ability, guild_id=state.guild_id)
    amount = dice_total + ability_mod + card.flat_modifier
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    healed = target.hp - before
    if target.hp > 0:
        target.death_save_successes = 0
        target.death_save_failures = 0
    _sync_hp_to_sheet(target, guild_id=state.guild_id)
    line = (
        f"**{actor.name}** soigne **{target.name}** avec **{card.label}** "
        f"— **{healed}** PV [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + card.flat_modifier)}]"
        f"{_hp_suffix(target)}"
    )
    _append_log(state, line)
    return line


def _consume_spell_slot(
    actor: CombatantState, card: CardSnapshot, *, guild_id: int
) -> None:
    if card.spell_level <= 0 or actor.user_id is None:
        return
    sheet = _sheet_for(actor, guild_id=guild_id)
    if sheet is None or not sheet.spell_slots.has_slots():
        return
    slot_level = sheet.spell_slots.lowest_available(card.spell_level)
    if slot_level is None:
        return

    def _use(current: CharacterSheet) -> None:
        current.spell_slots.use(level=slot_level)

    update_sheet(user_id=actor.user_id, guild_id=guild_id, updater=_use)


def _hp_suffix(combatant: CombatantState) -> str:
    if combatant.user_id is None:
        return ""
    return f" — **{combatant.hp}/{combatant.max_hp}** HP"


def _has_spell_slot(
    actor: CombatantState, card: CardSnapshot, *, guild_id: int
) -> bool:
    if card.spell_level <= 0:
        return True
    sheet = _sheet_for(actor, guild_id=guild_id)
    if sheet is None or not sheet.spell_slots.has_slots():
        return True
    return sheet.spell_slots.lowest_available(card.spell_level) is not None


async def start_combat(
    *,
    guild_id: int,
    channel_id: int,
    scope_id: int,
    map_id: str = "arena",
    restore_hp: bool = False,
) -> CombatState:
    initiative = get_initiative(guild_id=guild_id, scope_id=scope_id)
    if initiative is None or not initiative.order:
        raise ValueError(
            "Pas d’initiative. Utilise `;init add`, puis `;combat start`."
        )
    previous = get_combat(guild_id=guild_id, scope_id=scope_id)
    board_message_id = (
        previous.board_message_id if previous is not None else None
    )

    combatants: dict[str, CombatantState] = {}
    turn_order: list[str] = []

    for entry in initiative.order:
        sheet = (
            get_sheet(user_id=entry.user_id, guild_id=guild_id)
            if entry.user_id
            else None
        )
        monster = (
            await lookup_monster_profile(entry.name) if entry.user_id is None else None
        )
        if sheet:
            max_hp = sheet.hp_max if sheet.hp_max else DEFAULT_NPC_HP
            hp = sheet.hp_current if sheet.hp_current is not None else max_hp
            if restore_hp and max_hp and entry.user_id is not None:
                hp = max_hp
                update_sheet(
                    user_id=entry.user_id,
                    guild_id=guild_id,
                    updater=_restore_sheet_hp,
                )
        elif monster is not None:
            max_hp = monster.hp
            hp = monster.hp
        else:
            max_hp = DEFAULT_NPC_HP
            hp = DEFAULT_NPC_HP
        deck, catalog = await build_combatant_deck(sheet=sheet, monster=monster)
        combatant = CombatantState(
            name=entry.name,
            user_id=entry.user_id,
            hp=hp,
            max_hp=max_hp,
            hand=[],
            deck=deck,
            card_catalog=catalog,
            traits=list(monster.traits) if monster is not None else [],
            ac=sheet.ac
            if sheet
            else (monster.ac if monster is not None else DEFAULT_NPC_AC),
            attack_bonus=(
                0
                if sheet
                else (
                    monster.attack_bonus
                    if monster is not None
                    else DEFAULT_NPC_ATTACK_BONUS
                )
            ),
            death_save_successes=(
                0 if restore_hp else (sheet.death_save_successes if sheet else 0)
            ),
            death_save_failures=(
                0 if restore_hp else (sheet.death_save_failures if sheet else 0)
            ),
            speed=speed_for_sheet(sheet),
            attacks=monster.attacks if monster is not None else 1,
        )
        _shuffle_and_deal(combatant)
        combatants[entry.name.lower()] = combatant
        turn_order.append(entry.name)

    state = CombatState(
        guild_id=guild_id,
        channel_id=channel_id,
        scope_id=scope_id,
        turn_order=turn_order,
        active_index=initiative.active_index % len(turn_order),
        combatants=combatants,
        log=[combat_started()],
        board_message_id=board_message_id,
    )
    apply_template(state, map_id)
    _prepare_active_turn(state)
    save_combat(state)
    resolve_npc_turns(state)
    return state


async def add_combatant(
    state: CombatState,
    *,
    name: str,
    hp: int | None = None,
    user_id: int | None = None,
) -> CombatantState:
    key = name.lower()
    if key in state.combatants:
        raise ValueError(f"**{name}** est déjà dans ce combat.")

    sheet = get_sheet(user_id=user_id, guild_id=state.guild_id) if user_id else None
    monster = await lookup_monster_profile(name) if user_id is None else None
    if sheet:
        resolved_hp = (
            sheet.hp_current
            if sheet.hp_current is not None
            else sheet.hp_max or hp or DEFAULT_NPC_HP
        )
        max_hp = sheet.hp_max or resolved_hp
        name = sheet.name or name
        key = name.lower()
    elif monster is not None:
        resolved_hp = hp if hp is not None else monster.hp
        max_hp = resolved_hp
    else:
        resolved_hp = hp if hp is not None else DEFAULT_NPC_HP
        max_hp = resolved_hp

    deck, catalog = await build_combatant_deck(sheet=sheet, monster=monster)
    combatant = CombatantState(
        name=name,
        user_id=user_id,
        hp=resolved_hp,
        max_hp=max_hp,
        hand=[],
        deck=deck,
        card_catalog=catalog,
        traits=list(monster.traits) if monster is not None else [],
        ac=sheet.ac
        if sheet
        else (monster.ac if monster is not None else DEFAULT_NPC_AC),
        attack_bonus=(
            0
            if sheet
            else (
                monster.attack_bonus
                if monster is not None
                else DEFAULT_NPC_ATTACK_BONUS
            )
        ),
        death_save_successes=sheet.death_save_successes if sheet else 0,
        death_save_failures=sheet.death_save_failures if sheet else 0,
        speed=speed_for_sheet(sheet),
        attacks=monster.attacks if monster is not None else 1,
    )
    _shuffle_and_deal(combatant)
    state.combatants[key] = combatant
    if name not in state.turn_order:
        state.turn_order.append(name)
    place_new_combatant(state, combatant)
    save_combat(state)
    return combatant


def play_card(
    state: CombatState,
    *,
    actor_name: str,
    card_id: str,
    target_name: str | None = None,
) -> PlayResult:
    actor = state.find_combatant(actor_name)
    if actor is None:
        raise ValueError(combatant_missing(actor_name))

    card = lookup_card(actor.card_catalog, card_id)
    if card is None:
        raise ValueError(f"Carte inconnue `{card_id}`.")

    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(not_your_turn(str(state.active_name)))
    if actor.hp <= 0:
        return _skip_dying_turn(state, actor)
    if actor.acted:
        raise ValueError(already_acted(actor.name))

    in_hand = card_id in actor.hand
    if not in_hand and not is_spellbook_card(card):
        raise ValueError(f"**{actor.name}** n’a pas {card_label(card)} en main.")

    if card.card_type == "spell" and not _has_spell_slot(
        actor, card, guild_id=state.guild_id
    ):
        raise ValueError(
            f"Plus d’emplacements de niveau {card.spell_level}+ sur ta fiche."
        )

    if in_hand:
        actor.hand.remove(card_id)

    def _restore_hand() -> None:
        if in_hand:
            actor.hand.append(card_id)

    target: CombatantState | None = None
    aoe_center: tuple[int, int] | None = None
    if card_requires_target(card):
        if not target_name:
            _restore_hand()
            raise ValueError(f"{card.label} exige une cible.")
        cell = parse_cell(target_name, state)
        if card.aoe_radius and cell is not None:
            ensure_positions(state)
            if actor.x is None or actor.y is None:
                _restore_hand()
                raise ValueError(f"**{actor.name}** n’a pas de position sur la carte.")
            if chebyshev(actor.x, actor.y, cell[0], cell[1]) > (
                card.range_squares or 0
            ) and card.range_squares is not None:
                _restore_hand()
                raise ValueError(
                    out_of_range(
                        cell_label(*cell, state),
                        cell_label(*cell, state),
                        f"{card.range_squares} cases",
                    )
                )
            aoe_center = cell
        else:
            target = state.find_combatant(target_name)
            if target is None:
                _restore_hand()
                raise ValueError(f"Cible **{target_name}** introuvable.")
            if _is_eliminated(target):
                _restore_hand()
                raise ValueError(f"**{target.name}** est déjà vaincu.")
            if _is_self_target(actor, target) and _hostile_card(card):
                _restore_hand()
                raise ValueError(cannot_attack_self())
            ensure_positions(state)
            if not in_range(actor, target, card.range_squares):
                _restore_hand()
                dest = cell_label(target.x, target.y, state)
                reach = (
                    "mêlée (1 case)"
                    if card.range_squares == 1
                    else f"{card.range_squares} cases"
                    if card.range_squares is not None
                    else "portée"
                )
                raise ValueError(out_of_range(target.name, dest, reach))
            if card.aoe_radius and target.x is not None and target.y is not None:
                aoe_center = (target.x, target.y)
    else:
        target = actor

    message: str
    if card.card_type == "dodge":
        actor.effects.append(DODGE_CARD_ID)
        message = (
            f"**{actor.name}** choisit Esquive — les dégâts sont divisés par deux "
            "jusqu’à son prochain tour."
        )
        _append_log(state, message)
    elif aoe_center is not None and card.aoe_radius:
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        _begin_concentration(state, actor, card)
        message = _resolve_aoe_card(
            state, actor=actor, card=card, center=aoe_center
        )
    elif card.is_healing:
        assert target is not None
        _consume_spell_slot(actor, card, guild_id=state.guild_id)
        message = _resolve_heal_card(state, actor=actor, target=target, card=card)
    elif card.save_ability:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        _begin_concentration(state, actor, card)
        message = _resolve_save_card(state, actor=actor, target=target, card=card)
    elif card.dice_count > 0:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        _begin_concentration(state, actor, card)
        message = _resolve_damage_card(state, actor=actor, target=target, card=card)
    else:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        _begin_concentration(state, actor, card)
        if card_id not in target.effects:
            target.effects.append(card_id)
        buff = card_buff(card)
        if buff == "shield":
            message = (
                f"**{actor.name}** lance **{card.label}** sur **{target.name}** "
                "— le prochain coup est annulé."
            )
        elif buff == "mage-armor":
            message = (
                f"**{actor.name}** lance **{card.label}** sur **{target.name}** "
                "— les coups infligent 1d4 de moins."
            )
        elif buff == "bless":
            message = (
                f"**{actor.name}** lance **{card.label}** sur **{target.name}** "
                "— ses attaques infligent +1d4."
            )
        elif target.name.lower() == actor.name.lower():
            message = f"**{actor.name}** lance **{card.label}**."
        else:
            message = f"**{actor.name}** lance **{card.label}** sur **{target.name}**."
        _append_log(state, message)

    if in_hand:
        _discard_card(actor, card_id)

    actor.acted = True
    return _finish_action(state, message)


def _roll_death_save(state: CombatState, combatant: CombatantState) -> None:
    roll = random.randint(1, 20)
    if roll == 20:
        combatant.hp = 1
        combatant.death_save_successes = 0
        combatant.death_save_failures = 0
        _sync_hp_to_sheet(combatant, guild_id=state.guild_id)
        _append_log(
            state,
            f"**{combatant.name}** {CRIT_SUCCESS_LABEL} — jet de mort **20** "
            "— se relève avec 1 PV !",
        )
        return
    if roll == 1:
        combatant.death_save_failures += 2
        note = f"{CRIT_FAIL_LABEL} (deux échecs)"
    elif roll >= 10:
        combatant.death_save_successes += 1
        note = "réussite"
    else:
        combatant.death_save_failures += 1
        note = "échec"
    _sync_hp_to_sheet(combatant, guild_id=state.guild_id)
    _append_log(
        state,
        f"**{combatant.name}** jet de mort **{roll}** — {note} "
        f"({combatant.death_save_successes}R/{combatant.death_save_failures}E).",
    )
    if combatant.death_save_failures >= 3:
        _append_log(state, dies(combatant.name))
        _remove_from_turn_order(state, combatant.name.lower())
    elif combatant.death_save_successes >= 3:
        _append_log(state, stable(combatant.name))


def _handle_incapacitated_turn(state: CombatState, combatant: CombatantState) -> bool:
    if combatant.hp > 0:
        return True
    if combatant.user_id is None:
        return False
    if combatant.death_save_failures >= 3:
        _remove_from_turn_order(state, combatant.name.lower())
        return False
    if combatant.death_save_successes >= 3:
        _append_log(state, skips_stable(combatant.name))
        return False
    _roll_death_save(state, combatant)
    return combatant.hp > 0


def _end_turn(state: CombatState, actor: CombatantState) -> None:
    for _ in range(DRAW_PER_TURN):
        if len(actor.hand) >= HAND_SIZE:
            break
        drawn = _draw_card(actor)
        if drawn is None:
            break

    if not state.turn_order:
        return

    state.active_index = (state.active_index + 1) % len(state.turn_order)
    _prepare_active_turn(state)


def _prepare_active_turn(state: CombatState) -> None:
    seen: set[str] = set()
    while state.turn_order:
        active = state.active_combatant()
        if active is None:
            break
        key = active.name.lower()
        if key in seen:
            break
        _expire_turn_start_effects(active)
        active.moved = 0
        active.acted = False
        active.conditions = sorted(_condition_keys(active, guild_id=state.guild_id))
        stuck = _condition_keys(active, guild_id=state.guild_id) & SKIP_TURN_CONDITIONS
        if active.hp > 0 and not stuck:
            break
        if active.hp > 0 and stuck:
            label = next(iter(stuck))
            _append_log(state, skips_condition(active.name, label))
            seen.add(key)
            if not state.turn_order:
                break
            if active.name not in state.turn_order:
                continue
            state.active_index = (state.active_index + 1) % len(state.turn_order)
            continue
        seen.add(key)
        _handle_incapacitated_turn(state, active)
        if active.hp > 0:
            break
        if not state.turn_order:
            break
        if active.name not in state.turn_order:
            continue
        state.active_index = (state.active_index + 1) % len(state.turn_order)


def _skip_dying_turn(state: CombatState, actor: CombatantState) -> PlayResult:
    result = finish_turn(state, actor_name=actor.name)
    prefix = dying_skip(actor.name, PREFIX)
    if result.message:
        return PlayResult(
            message=f"{prefix}\n{result.message}",
            combat_over=result.combat_over,
            winner=result.winner,
        )
    return PlayResult(
        message=prefix, combat_over=result.combat_over, winner=result.winner
    )


def end_turn(state: CombatState, *, actor_name: str) -> PlayResult:
    actor = state.find_combatant(actor_name)
    if actor is None:
        raise ValueError(combatant_missing(actor_name))
    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(not_your_turn(str(state.active_name)))
    _append_log(state, ends_turn(actor.name))
    _end_turn(state, actor)
    result = _finish_action(state, "")
    if result.combat_over:
        return result
    return PlayResult(message=turn_passed(str(state.active_name)))


def valid_targets(
    state: CombatState, *, actor: CombatantState, card_id: str
) -> list[CombatantState]:
    card = lookup_card(actor.card_catalog, card_id)
    if card is None:
        return []
    living = [
        combatant for combatant in state.combatants.values() if _in_fight(combatant)
    ]
    if _hostile_card(card):
        living = [combatant for combatant in living if combatant is not actor]
    ensure_positions(state)
    return [
        combatant
        for combatant in living
        if in_range(actor, combatant, card.range_squares)
    ]


def _require_active_actor(state: CombatState, actor_name: str) -> CombatantState:
    actor = state.find_combatant(actor_name)
    if actor is None:
        raise ValueError(combatant_missing(actor_name))
    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(not_your_turn(str(state.active_name)))
    ensure_positions(state)
    return actor


def _melee_threatens(enemy: CombatantState, x: int, y: int) -> bool:
    if enemy.x is None or enemy.y is None or _is_eliminated(enemy):
        return False
    return chebyshev(enemy.x, enemy.y, x, y) <= 1


def _opportunity_attackers(
    state: CombatState,
    mover: CombatantState,
    from_cell: tuple[int, int],
    to_cell: tuple[int, int],
) -> list[CombatantState]:
    found: list[CombatantState] = []
    for enemy in state.combatants.values():
        if enemy is mover or _same_side(enemy, mover) or not occupies_cell(enemy):
            continue
        if _melee_threatens(enemy, from_cell[0], from_cell[1]) and not _melee_threatens(
            enemy, to_cell[0], to_cell[1]
        ):
            found.append(enemy)
    return found


def move_combatant(
    state: CombatState,
    *,
    actor_name: str,
    dest_x: int,
    dest_y: int,
) -> PlayResult:
    actor = _require_active_actor(state, actor_name)
    if actor.hp <= 0:
        return _skip_dying_turn(state, actor)
    if actor.x is None or actor.y is None:
        raise ValueError(f"**{actor.name}** n’a pas de position sur la carte.")
    if actor.x == dest_x and actor.y == dest_y:
        raise ValueError(f"**{actor.name}** est déjà sur {cell_label(dest_x, dest_y, state)}.")
    blocked = movement_blockers(actor)
    if blocked:
        raise ValueError(cannot_move(next(iter(blocked))))
    cells = path_cells(state, actor, dest_x, dest_y)
    cost = path_length(state, actor, dest_x, dest_y)
    if cells is None or cost is None:
        raise ValueError(cannot_reach(cell_label(dest_x, dest_y, state)))
    left = remaining_squares(actor)
    if cost > left:
        raise ValueError(not_enough_move(cost, cell_label(dest_x, dest_y, state), left))
    parts: list[str] = []
    origin = (actor.x, actor.y)
    for step in cells:
        leavers = _opportunity_attackers(state, actor, origin, step)
        for enemy in leavers:
            try:
                result = map_attack(
                    state,
                    actor_name=enemy.name,
                    target_name=actor.name,
                    consume_action=False,
                    opportunity=True,
                )
            except ValueError:
                continue
            note = opportunity(enemy.name, actor.name)
            _append_log(state, note)
            parts.append(note)
            parts.append(result.message)
            if result.combat_over:
                return PlayResult(
                    message="\n".join(parts),
                    combat_over=True,
                    winner=result.winner,
                )
            if actor.hp <= 0 or _is_eliminated(actor):
                save_combat(state)
                return PlayResult(message="\n".join(parts))
        actor.x, actor.y = step
        actor.moved += 1
        origin = step
    message = moves_to(
        actor.name, cell_label(dest_x, dest_y, state), remaining_squares(actor)
    )
    _append_log(state, message)
    parts.append(message)
    save_combat(state)
    return PlayResult(message="\n".join(parts))


def map_attack(
    state: CombatState,
    *,
    actor_name: str,
    target_name: str,
    consume_action: bool = True,
    opportunity: bool = False,
) -> PlayResult:
    if opportunity:
        actor = state.find_combatant(actor_name)
        if actor is None:
            raise ValueError(combatant_missing(actor_name))
        ensure_positions(state)
    else:
        actor = _require_active_actor(state, actor_name)
        if actor.hp <= 0:
            return _skip_dying_turn(state, actor)
        if actor.acted:
            raise ValueError(already_attacked(actor.name))
    target = state.find_combatant(target_name)
    if target is None:
        raise ValueError(f"Cible **{target_name}** introuvable.")
    if _is_eliminated(target):
        raise ValueError(f"**{target.name}** est déjà vaincu.")
    if _is_self_target(actor, target):
        raise ValueError(cannot_attack_self())
    card = lookup_card(actor.card_catalog, WEAPON_CARD_ID)
    if card is None:
        raise ValueError(f"**{actor.name}** n’a pas d’attaque d’arme.")
    reach = 1 if opportunity else weapon_range_squares(actor)
    if not in_range(actor, target, reach):
        dest = cell_label(target.x, target.y, state)
        raise ValueError(out_of_range(target.name, dest, f"{reach} cases"))
    message = _resolve_damage_card(state, actor=actor, target=target, card=card)
    if consume_action:
        actor.acted = True
    return _finish_action(state, message)


def enemies_in_weapon_range(
    state: CombatState, actor: CombatantState
) -> list[CombatantState]:
    ensure_positions(state)
    return targets_in_range(state, actor, weapon_range_squares(actor))


def attack_targets_in_weapon_range(
    state: CombatState, actor: CombatantState
) -> list[CombatantState]:
    ensure_positions(state)
    return attack_targets_in_range(state, actor, weapon_range_squares(actor))


def enemies_in_melee(state: CombatState, actor: CombatantState) -> list[CombatantState]:
    return enemies_in_weapon_range(state, actor)


def _nearest_enemy(
    state: CombatState, actor: CombatantState
) -> CombatantState | None:
    living = [
        combatant
        for combatant in state.combatants.values()
        if combatant is not actor
        and occupies_cell(combatant)
        and not _same_side(actor, combatant)
    ]
    if not living:
        return None
    ranked: list[tuple[int, CombatantState]] = []
    for combatant in living:
        dist = distance_squares(actor, combatant)
        ranked.append((99 if dist is None else dist, combatant))
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def play_npc_turn(state: CombatState) -> PlayResult:
    actor = state.active_combatant()
    if actor is None or actor.user_id is not None:
        raise ValueError("Ce n’est pas le tour d’un monstre.")
    ensure_positions(state)
    parts: list[str] = []
    reach = weapon_range_squares(actor)
    ranged = reach > 1
    nearby = enemies_in_weapon_range(state, actor)
    if ranged and melee_targets(state, actor) and remaining_squares(actor):
        prey = _nearest_enemy(state, actor)
        dest = (
            best_move_toward(state, actor, prey, keep_distance=True)
            if prey is not None
            else None
        )
        if dest is not None and (dest[0] != actor.x or dest[1] != actor.y):
            moved = move_combatant(
                state, actor_name=actor.name, dest_x=dest[0], dest_y=dest[1]
            )
            parts.append(moved.message)
            if moved.combat_over:
                return moved
        nearby = enemies_in_weapon_range(state, actor)
    if not nearby:
        prey = _nearest_enemy(state, actor)
        dest = (
            best_move_toward(state, actor, prey, keep_distance=ranged)
            if prey is not None
            else None
        )
        if dest is not None and (dest[0] != actor.x or dest[1] != actor.y):
            moved = move_combatant(
                state, actor_name=actor.name, dest_x=dest[0], dest_y=dest[1]
            )
            parts.append(moved.message)
            if moved.combat_over:
                return moved
        nearby = enemies_in_weapon_range(state, actor)
    attacks_left = max(1, actor.attacks)
    while nearby and attacks_left > 0:
        target = nearby[0]
        prey = _nearest_enemy(state, actor)
        if prey is not None and prey in nearby:
            target = prey
        struck = map_attack(
            state,
            actor_name=actor.name,
            target_name=target.name,
            consume_action=False,
        )
        parts.append(struck.message)
        attacks_left -= 1
        if struck.combat_over:
            actor.acted = True
            return struck
        nearby = enemies_in_weapon_range(state, actor)
    if attacks_left < max(1, actor.attacks):
        actor.acted = True
        save_combat(state)
    done = end_turn(state, actor_name=actor.name)
    parts.append(done.message)
    return PlayResult(
        message="\n".join(parts),
        combat_over=done.combat_over,
        winner=done.winner,
    )


def resolve_npc_turns(state: CombatState) -> PlayResult:
    parts: list[str] = []
    seen: set[str] = set()
    winner = None
    while True:
        active = state.active_combatant()
        if active is None or active.user_id is not None:
            break
        key = active.name.lower()
        if key in seen:
            break
        seen.add(key)
        result = play_npc_turn(state)
        if result.message:
            parts.append(result.message)
        if result.combat_over:
            return result
        winner = result.winner
    message = "\n".join(parts)
    return PlayResult(message=message, winner=winner)


def finish_turn(state: CombatState, *, actor_name: str) -> PlayResult:
    result = end_turn(state, actor_name=actor_name)
    if result.combat_over:
        return result
    follow = resolve_npc_turns(state)
    if not follow.message:
        return result
    return PlayResult(
        message=f"{result.message}\n{follow.message}",
        combat_over=follow.combat_over,
        winner=follow.winner or result.winner,
    )
