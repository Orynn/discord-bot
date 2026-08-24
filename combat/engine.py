import random
from dataclasses import dataclass

from combat.cards import (
    BUFF_BY_SLUG,
    DODGE_CARD_ID,
    DRAW_PER_TURN,
    HAND_SIZE,
    MAX_LOG_LINES,
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
from combat.monsters import lookup_monster_profile
from combat.storage import CombatState, CombatantState, save_combat
from initiative.storage import get_initiative
from sheets.conditions import (
    ATTACKER_DISADVANTAGE,
    DEFENDER_ADVANTAGE,
    sheet_condition_keys,
)
from sheets.data import CharacterSheet, ability_modifier
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


def can_control_combatant(
    *,
    combatant: CombatantState,
    user_id: int,
    is_admin: bool,
    scope_id: int | None = None,
) -> bool:
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
    return f" — {key}"


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


def _attack_advantage(
    actor: CombatantState, target: CombatantState, *, guild_id: int
) -> bool | None:
    actor_keys = _condition_keys(actor, guild_id=guild_id)
    target_keys = _condition_keys(target, guild_id=guild_id)
    disadv = bool(actor_keys & ATTACKER_DISADVANTAGE)
    adv = bool(target_keys & DEFENDER_ADVANTAGE)
    if adv and disadv:
        return None
    if adv:
        return True
    if disadv:
        return False
    return None


def _roll_d20(advantage: bool | None) -> tuple[int, str]:
    if advantage is None:
        roll = random.randint(1, 20)
        return roll, str(roll)
    first = random.randint(1, 20)
    second = random.randint(1, 20)
    chosen = max(first, second) if advantage else min(first, second)
    tag = "adv" if advantage else "dis"
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
    advantage = _attack_advantage(actor, target, guild_id=state.guild_id)
    roll, roll_note = _roll_d20(advantage)
    total = roll + bonus
    bonus_note = f"{bonus:+d}" if bonus else "+0"
    if roll == 1:
        return False, False, f"{roll_note}{bonus_note} vs AC {ac} — miss (nat 1)"
    if roll == 20:
        return True, True, f"{roll_note}{bonus_note} vs AC {ac} — hit (nat 20)"
    hit = total >= ac
    verb = "hit" if hit else "miss"
    return hit, False, f"{roll_note}{bonus_note} vs AC {ac} — {verb}"


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


def _sync_hp_to_sheet(combatant: CombatantState, *, guild_id: int) -> None:
    if combatant.user_id is None:
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


def _living_combatants(state: CombatState) -> list[CombatantState]:
    return [
        combatant for combatant in state.combatants.values() if _in_fight(combatant)
    ]


def _check_victory(state: CombatState) -> PlayResult | None:
    living = _living_combatants(state)
    if not living:
        _append_log(state, "Everyone is down — combat ends.")
        return PlayResult(message="Combat ended with no survivors.", combat_over=True)
    living_sides = {_side(combatant) for combatant in living}
    if len(living_sides) != 1:
        return None
    if len({_side(combatant) for combatant in state.combatants.values()}) < 2:
        return None
    if living_sides == {"pc"}:
        if len(living) == 1:
            winner = living[0].name
            message = f"**{winner}** wins the card combat!"
        else:
            winner = "the party"
            message = "The party wins the card combat!"
    elif len(living) == 1:
        winner = living[0].name
        message = f"**{winner}** wins the card combat!"
    else:
        winner = "the monsters"
        message = "The monsters win the card combat!"
    _append_log(state, message.rstrip("!") + "!")
    return PlayResult(message=message, combat_over=True, winner=winner)


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
        notes.append("Shield: negated")
    else:
        if DODGE_CARD_ID in target.effects:
            amount = amount // 2
            notes.append("Dodge: half")
        if _has_buff(target, "mage-armor"):
            reduction, _ = _roll_dice(1, 4)
            amount = max(0, amount - reduction)
            notes.append(f"Mage Armor -{reduction}")

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
        f"**{source.name}** uses **{action_label}** on **{target.name}** "
        f"for **{amount}**{type_part} damage{note}"
        f"{_hp_suffix(target)}"
    )
    _append_log(state, line)

    if target.user_id is None:
        if target.hp <= 0:
            _append_log(state, f"**{target.name}** is defeated!")
            _remove_from_turn_order(state, target.name.lower())
    elif target.hp <= 0:
        if extra_save:
            _append_log(
                state,
                f"**{target.name}** takes a death-save failure "
                f"({target.death_save_successes}S/{target.death_save_failures}F).",
            )
        else:
            _append_log(state, f"**{target.name}** drops to 0 HP and is dying.")
        if target.death_save_failures >= 3:
            _append_log(state, f"**{target.name}** dies.")
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
                f"**{actor.name}** uses **{card.label}** on **{target.name}** "
                f"— miss ({attack_note})"
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
    outcome = "success" if success else "fail"
    save_note = f"{ability.upper()} {roll_note}{bonus_note} vs DC {dc} — {outcome}"

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
            extra_notes.append("half")
        elif success:
            amount = 0
            extra_notes.append("no damage")
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
            _append_log(state, f"**{target.name}** is {card.inflict_condition}.")
        return line

    if success:
        line = f"**{target.name}** resists **{card.label}** ({save_note})"
        _append_log(state, line)
        return line

    extra = ""
    if card.inflict_condition:
        extra = _apply_condition(state, target, card.inflict_condition)
    line = (
        f"**{actor.name}** casts **{card.label}** on **{target.name}** "
        f"— {save_note}{extra}"
    )
    _append_log(state, line)
    return line


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
        f"**{actor.name}** casts **{card.label}** on **{target.name}** "
        f"for **{healed}** HP [{_format_dice_note(rolls=dice_rolls, modifier=ability_mod + card.flat_modifier)}]"
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


async def start_combat(*, guild_id: int, channel_id: int, scope_id: int) -> CombatState:
    initiative = get_initiative(guild_id=guild_id, scope_id=scope_id)
    if initiative is None or not initiative.order:
        raise ValueError(
            "No initiative tracked. Use `;init add` first, then `;combat start`."
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
            death_save_successes=sheet.death_save_successes if sheet else 0,
            death_save_failures=sheet.death_save_failures if sheet else 0,
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
        log=[
            "Card combat started — decks built from character sheets and your 5etools export."
        ],
    )
    save_combat(state)
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
        raise ValueError(f"**{name}** is already in this combat.")

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
    if actor.hp <= 0:
        raise ValueError(f"**{actor.name}** is dying and cannot act.")

    in_hand = card_id in actor.hand
    if not in_hand and not is_spellbook_card(card):
        raise ValueError(f"**{actor.name}** does not have {card_label(card)} in hand.")

    if card.card_type == "spell" and not _has_spell_slot(
        actor, card, guild_id=state.guild_id
    ):
        raise ValueError(
            f"No level {card.spell_level}+ spell slots remaining on your sheet."
        )

    if in_hand:
        actor.hand.remove(card_id)

    def _restore_hand() -> None:
        if in_hand:
            actor.hand.append(card_id)

    target: CombatantState | None = None
    if card_requires_target(card):
        if not target_name:
            _restore_hand()
            raise ValueError(f"{card.label} requires a target.")
        target = state.find_combatant(target_name)
        if target is None:
            _restore_hand()
            raise ValueError(f"Target **{target_name}** not found.")
        if _is_eliminated(target):
            _restore_hand()
            raise ValueError(f"**{target.name}** is already defeated.")
        if card.target_enemies_only and _same_side(actor, target):
            _restore_hand()
            raise ValueError("Pick an enemy target.")
        if card.target_allies_only and not _same_side(actor, target):
            _restore_hand()
            raise ValueError("Pick an allied target.")
    else:
        target = actor

    message: str
    if card.card_type == "dodge":
        actor.effects.append(DODGE_CARD_ID)
        message = f"**{actor.name}** takes the Dodge action — damage is halved until their next turn."
        _append_log(state, message)
    elif card.is_healing:
        assert target is not None
        _consume_spell_slot(actor, card, guild_id=state.guild_id)
        message = _resolve_heal_card(state, actor=actor, target=target, card=card)
    elif card.save_ability:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        message = _resolve_save_card(state, actor=actor, target=target, card=card)
    elif card.dice_count > 0:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        message = _resolve_damage_card(state, actor=actor, target=target, card=card)
    else:
        assert target is not None
        if card.card_type == "spell":
            _consume_spell_slot(actor, card, guild_id=state.guild_id)
        if card_id not in target.effects:
            target.effects.append(card_id)
        buff = card_buff(card)
        if buff == "shield":
            message = (
                f"**{actor.name}** casts **{card.label}** on **{target.name}** "
                "— the next hit is negated."
            )
        elif buff == "mage-armor":
            message = (
                f"**{actor.name}** casts **{card.label}** on **{target.name}** "
                "— hits deal 1d4 less."
            )
        elif buff == "bless":
            message = (
                f"**{actor.name}** casts **{card.label}** on **{target.name}** "
                "— their attacks deal +1d4."
            )
        elif target.name.lower() == actor.name.lower():
            message = f"**{actor.name}** casts **{card.label}**."
        else:
            message = f"**{actor.name}** casts **{card.label}** on **{target.name}**."
        _append_log(state, message)

    if in_hand:
        _discard_card(actor, card_id)

    victory = _check_victory(state)
    if victory is not None:
        save_combat(state)
        return victory

    _end_turn(state, actor)
    later = _check_victory(state)
    save_combat(state)
    if later is not None:
        return PlayResult(
            message=f"{message}\n{later.message}",
            combat_over=True,
            winner=later.winner,
        )
    return PlayResult(message=message)


def _roll_death_save(state: CombatState, combatant: CombatantState) -> None:
    roll = random.randint(1, 20)
    if roll == 20:
        combatant.hp = 1
        combatant.death_save_successes = 0
        combatant.death_save_failures = 0
        _sync_hp_to_sheet(combatant, guild_id=state.guild_id)
        _append_log(
            state, f"**{combatant.name}** death save **{roll}** — gets up with 1 HP!"
        )
        return
    if roll == 1:
        combatant.death_save_failures += 2
        note = "nat 1 (two failures)"
    elif roll >= 10:
        combatant.death_save_successes += 1
        note = "success"
    else:
        combatant.death_save_failures += 1
        note = "failure"
    _sync_hp_to_sheet(combatant, guild_id=state.guild_id)
    _append_log(
        state,
        f"**{combatant.name}** death save **{roll}** — {note} "
        f"({combatant.death_save_successes}S/{combatant.death_save_failures}F).",
    )
    if combatant.death_save_failures >= 3:
        _append_log(state, f"**{combatant.name}** dies.")
        _remove_from_turn_order(state, combatant.name.lower())
    elif combatant.death_save_successes >= 3:
        _append_log(state, f"**{combatant.name}** is stable.")


def _handle_incapacitated_turn(state: CombatState, combatant: CombatantState) -> bool:
    if combatant.hp > 0:
        return True
    if combatant.user_id is None:
        return False
    if combatant.death_save_failures >= 3:
        _remove_from_turn_order(state, combatant.name.lower())
        return False
    if combatant.death_save_successes >= 3:
        _append_log(state, f"**{combatant.name}** is stable and skips their turn.")
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
    seen: set[str] = set()
    while state.turn_order:
        active = state.active_combatant()
        if active is None:
            break
        key = active.name.lower()
        if key in seen:
            break
        _expire_turn_start_effects(active)
        stuck = _condition_keys(active, guild_id=state.guild_id) & SKIP_TURN_CONDITIONS
        if active.hp > 0 and not stuck:
            break
        if active.hp > 0 and stuck:
            label = next(iter(stuck))
            _append_log(state, f"**{active.name}** is {label} and skips their turn.")
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


def end_turn(state: CombatState, *, actor_name: str) -> PlayResult:
    actor = state.find_combatant(actor_name)
    if actor is None:
        raise ValueError(f"Combatant **{actor_name}** not found.")
    active = state.active_combatant()
    if active is None or active.name.lower() != actor.name.lower():
        raise ValueError(f"It is **{state.active_name}**'s turn.")
    _append_log(state, f"**{actor.name}** ends their turn.")
    _end_turn(state, actor)
    victory = _check_victory(state)
    save_combat(state)
    if victory is not None:
        return victory
    return PlayResult(message=f"Turn passed to **{state.active_name}**.")


def valid_targets(
    state: CombatState, *, actor: CombatantState, card_id: str
) -> list[CombatantState]:
    card = lookup_card(actor.card_catalog, card_id)
    if card is None:
        return []
    living = [
        combatant for combatant in state.combatants.values() if _in_fight(combatant)
    ]
    if card.target_enemies_only:
        return [combatant for combatant in living if not _same_side(actor, combatant)]
    if card.target_allies_only:
        return [combatant for combatant in living if _same_side(actor, combatant)]
    return living
