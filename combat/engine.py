import random
from dataclasses import dataclass

from combat.cards import (
    DODGE_CARD_ID,
    DRAW_PER_TURN,
    HAND_SIZE,
    MAX_LOG_LINES,
    CardSnapshot,
    card_label,
    lookup_card,
)
from combat.deck import build_combatant_deck
from combat.storage import CombatState, CombatantState, save_combat
from initiative.storage import get_initiative
from sheets.data import CharacterSheet, ability_modifier
from sheets.storage import get_sheet, update_sheet

DEFAULT_NPC_HP = 20


@dataclass(frozen=True)
class PlayResult:
    message: str
    combat_over: bool = False
    winner: str | None = None


def _sheet_for(combatant: CombatantState) -> CharacterSheet | None:
    if combatant.user_id is None:
        return None
    return get_sheet(user_id=combatant.user_id)


def _ability_mod(combatant: CombatantState, ability: str | None) -> int:
    if not ability:
        return 0
    sheet = _sheet_for(combatant)
    if sheet is None:
        return 0
    return ability_modifier(sheet.abilities[ability])


def _prof_bonus(combatant: CombatantState) -> int:
    sheet = _sheet_for(combatant)
    if sheet is None:
        return 0
    return sheet.get_prof_bonus()


def _roll_dice(count: int, sides: int) -> tuple[int, list[int]]:
    if count <= 0 or sides <= 0:
        return 0, []
    rolls = [random.randint(1, sides) for _ in range(count)]
    return sum(rolls), rolls


def _append_log(state: CombatState, line: str) -> None:
    state.log.append(line)
    if len(state.log) > MAX_LOG_LINES:
        state.log = state.log[-MAX_LOG_LINES:]


def _shuffle_and_deal(combatant: CombatantState) -> None:
    random.shuffle(combatant.deck)
    while len(combatant.hand) < HAND_SIZE and combatant.deck:
        combatant.hand.append(combatant.deck.pop())


def _draw_card(combatant: CombatantState) -> str | None:
    if not combatant.deck:
        return None
    card_id = combatant.deck.pop()
    combatant.hand.append(card_id)
    return card_id


def _sync_hp_to_sheet(combatant: CombatantState) -> None:
    if combatant.user_id is None:
        return

    def _apply(sheet: CharacterSheet) -> None:
        sheet.hp_current = combatant.hp

    update_sheet(combatant.user_id, _apply)


def _living_combatants(state: CombatState) -> list[CombatantState]:
    return [combatant for combatant in state.combatants.values() if combatant.hp > 0]


def _check_victory(state: CombatState) -> PlayResult | None:
    living = _living_combatants(state)
    if len(living) == 1:
        winner = living[0].name
        _append_log(state, f"**{winner}** wins the fight!")
        return PlayResult(message=f"**{winner}** wins the card combat!", combat_over=True, winner=winner)
    if not living:
        _append_log(state, "Everyone is down — combat ends.")
        return PlayResult(message="Combat ended with no survivors.", combat_over=True)
    return None


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
    if DODGE_CARD_ID in target.effects:
        target.effects.remove(DODGE_CARD_ID)
        amount = amount // 2
        dodge_note = " (Dodge: half damage)"
    else:
        dodge_note = ""

    target.hp = max(0, target.hp - amount)
    _sync_hp_to_sheet(target)
    type_part = f" {damage_type_label}" if damage_type_label else ""
    line = (
        f"**{source.name}** uses **{action_label}** on **{target.name}** "
        f"for **{amount}**{type_part} damage{dodge_note} — **{target.hp}/{target.max_hp}** HP"
    )
    _append_log(state, line)

    if target.hp <= 0:
        _append_log(state, f"**{target.name}** is defeated!")
        _remove_from_turn_order(state, target.name.lower())

    return line


def _resolve_damage_card(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> str:
    dice_total, dice_rolls = _roll_dice(card.dice_count, card.dice_sides)
    ability_mod = _ability_mod(actor, card.ability)
    prof = _prof_bonus(actor) if card.uses_proficiency else 0
    total = dice_total + ability_mod + prof + card.flat_modifier
    mod_parts = []
    if ability_mod:
        mod_parts.append(f"{card.ability.upper()} {ability_mod:+d}" if card.ability else str(ability_mod))
    if prof:
        mod_parts.append(f"prof +{prof}")
    if card.flat_modifier:
        mod_parts.append(str(card.flat_modifier))
    mod_note = f" ({', '.join(mod_parts)})" if mod_parts else ""
    action_label = f"{card.label} [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + prof + card.flat_modifier)}]{mod_note}"
    return _apply_damage(
        state,
        source=actor,
        target=target,
        amount=total,
        action_label=action_label,
        damage_type_label=card.damage_type_label,
    )


def _resolve_heal_card(
    state: CombatState,
    *,
    actor: CombatantState,
    target: CombatantState,
    card: CardSnapshot,
) -> str:
    dice_total, dice_rolls = _roll_dice(card.dice_count, card.dice_sides)
    ability_mod = _ability_mod(actor, card.ability)
    amount = dice_total + ability_mod + card.flat_modifier
    before = target.hp
    target.hp = min(target.max_hp, target.hp + amount)
    healed = target.hp - before
    _sync_hp_to_sheet(target)
    line = (
        f"**{actor.name}** casts **{card.label}** on **{target.name}** "
        f"for **{healed}** HP [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + card.flat_modifier)}] "
        f"— **{target.hp}/{target.max_hp}** HP"
    )
    _append_log(state, line)
    return line


def _consume_spell_slot(actor: CombatantState, card: CardSnapshot) -> None:
    if card.spell_level <= 0 or actor.user_id is None:
        return
    sheet = _sheet_for(actor)
    if sheet is None or not sheet.spell_slots.has_slots():
        return

    def _use(current: CharacterSheet) -> None:
        current.spell_slots.use(level=card.spell_level)

    update_sheet(actor.user_id, _use)


def _has_spell_slot(actor: CombatantState, card: CardSnapshot) -> bool:
    if card.spell_level <= 0:
        return True
    sheet = _sheet_for(actor)
    if sheet is None or not sheet.spell_slots.has_slots():
        return True
    remaining = sheet.spell_slots.get_current(card.spell_level)
    return remaining > 0


async def start_combat(*, guild_id: int, channel_id: int) -> CombatState:
    initiative = get_initiative(guild_id=guild_id)
    if initiative is None or not initiative.order:
        raise ValueError("No initiative tracked. Use `;init add` first, then `;combat start`.")

    combatants: dict[str, CombatantState] = {}
    turn_order: list[str] = []

    for entry in initiative.order:
        sheet = get_sheet(user_id=entry.user_id) if entry.user_id else None
        max_hp = sheet.hp_max if sheet and sheet.hp_max else DEFAULT_NPC_HP
        hp = sheet.hp_current if sheet and sheet.hp_current is not None else max_hp
        deck, catalog = await build_combatant_deck(sheet=sheet)
        combatant = CombatantState(
            name=entry.name,
            user_id=entry.user_id,
            hp=hp,
            max_hp=max_hp,
            hand=[],
            deck=deck,
            card_catalog=catalog,
        )
        _shuffle_and_deal(combatant)
        combatants[entry.name.lower()] = combatant
        turn_order.append(entry.name)

    state = CombatState(
        guild_id=guild_id,
        channel_id=channel_id,
        turn_order=turn_order,
        active_index=initiative.active_index % len(turn_order),
        combatants=combatants,
        log=["Card combat started — decks built from character sheets and your 5etools export."],
    )
    save_combat(state)
    return state


async def add_combatant(
    state: CombatState,
    *,
    name: str,
    hp: int,
    user_id: int | None = None,
) -> CombatantState:
    key = name.lower()
    if key in state.combatants:
        raise ValueError(f"**{name}** is already in this combat.")

    sheet = get_sheet(user_id=user_id) if user_id else None
    if sheet:
        hp = sheet.hp_current if sheet.hp_current is not None else sheet.hp_max or hp
        max_hp = sheet.hp_max or hp
        name = sheet.name or name
        key = name.lower()
    else:
        max_hp = hp

    deck, catalog = await build_combatant_deck(sheet=sheet)
    combatant = CombatantState(
        name=name,
        user_id=user_id,
        hp=hp,
        max_hp=max_hp,
        hand=[],
        deck=deck,
        card_catalog=catalog,
    )
    _shuffle_and_deal(combatant)
    state.combatants[key] = combatant
    if name not in state.turn_order:
        state.turn_order.append(name)
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
        raise ValueError(f"Combatant **{actor_name}** not found.")

    card = lookup_card(actor.card_catalog, card_id)
    if card is None:
        raise ValueError(f"Unknown card `{card_id}`.")

    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(f"It is **{state.active_name}**'s turn.")

    if card_id not in actor.hand:
        raise ValueError(f"**{actor.name}** does not have {card_label(card)} in hand.")

    if card.card_type == "spell" and not _has_spell_slot(actor, card):
        raise ValueError(f"No level {card.spell_level} spell slots remaining on your sheet.")

    actor.hand.remove(card_id)

    target: CombatantState | None = None
    if card.needs_target:
        if not target_name:
            actor.hand.append(card_id)
            raise ValueError(f"{card.label} requires a target.")
        target = state.find_combatant(target_name)
        if target is None:
            actor.hand.append(card_id)
            raise ValueError(f"Target **{target_name}** not found.")
        if target.hp <= 0:
            actor.hand.append(card_id)
            raise ValueError(f"**{target.name}** is already defeated.")
        if card.target_enemies_only and target.name.lower() == actor.name.lower():
            actor.hand.append(card_id)
            raise ValueError("Pick an enemy target.")
    else:
        target = actor

    message: str
    if card.card_type == "dodge":
        actor.effects.append(DODGE_CARD_ID)
        message = f"**{actor.name}** takes the Dodge action (SRD)."
        _append_log(state, message)
    elif card.is_healing:
        assert target is not None
        _consume_spell_slot(actor, card)
        message = _resolve_heal_card(state, actor=actor, target=target, card=card)
    elif card.dice_count > 0 and card.target_enemies_only:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card)
        message = _resolve_damage_card(state, actor=actor, target=target, card=card)
    elif card.dice_count > 0:
        assert target is not None
        message = _resolve_damage_card(state, actor=actor, target=target, card=card)
    else:
        actor.hand.append(card_id)
        raise ValueError(f"**{card.label}** cannot be resolved automatically.")

    victory = _check_victory(state)
    if victory is not None:
        save_combat(state)
        return victory

    _end_turn(state, actor)
    save_combat(state)
    return PlayResult(message=message)


def _end_turn(state: CombatState, actor: CombatantState) -> None:
    for _ in range(DRAW_PER_TURN):
        drawn = _draw_card(actor)
        if drawn is None:
            break

    if not state.turn_order:
        return

    state.active_index = (state.active_index + 1) % len(state.turn_order)
    while state.turn_order:
        active = state.active_combatant()
        if active is not None and active.hp > 0:
            break
        state.active_index = (state.active_index + 1) % len(state.turn_order)


def end_turn(state: CombatState, *, actor_name: str) -> PlayResult:
    actor = state.find_combatant(actor_name)
    if actor is None:
        raise ValueError(f"Combatant **{actor_name}** not found.")
    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(f"It is **{state.active_name}**'s turn.")
    _append_log(state, f"**{actor.name}** ends their turn.")
    _end_turn(state, actor)
    save_combat(state)
    return PlayResult(message=f"Turn passed to **{state.active_name}**.")


def valid_targets(state: CombatState, *, actor: CombatantState, card_id: str) -> list[CombatantState]:
    card = lookup_card(actor.card_catalog, card_id)
    if card is None:
        return []
    living = [combatant for combatant in state.combatants.values() if combatant.hp > 0]
    if card.target_enemies_only:
        return [combatant for combatant in living if combatant.name.lower() != actor.name.lower()]
    if card.target_allies_only:
        return living
    return living
