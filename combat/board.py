from combat.cards import is_spellbook_card, lookup_card
from combat.discord_sync import sync_combat_message
from combat.engine import finish_turn, map_attack, move_combatant, play_card
from combat.web_commands import run_web_command
from combat.map import (
    cell_label,
    ensure_positions,
    map_height,
    map_width,
    parse_cell,
    attack_targets_in_range,
    reachable_cells,
    remaining_squares,
    same_side,
    speed_squares,
    weapon_range_squares,
)
from combat.storage import CombatState, CombatantState, get_combat, lock_for
from combat.templates import template_for_state
from combat.text import classify_log_line
from config import PREFIX


def token_initials(name: str) -> str:
    parts = [part for part in name.replace("_", " ").split() if part]
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    cleaned = "".join(char for char in name if char.isalnum())
    return (cleaned[:2] or "?").upper()


def _is_down(combatant: CombatantState) -> bool:
    if combatant.user_id is None:
        return combatant.hp <= 0
    return combatant.hp <= 0 or combatant.death_save_failures >= 3


def _plain(text: str) -> str:
    return text.replace("**", "")


def _log_entry(line: str) -> dict:
    kind, emoji = classify_log_line(line)
    return {"text": _plain(line), "kind": kind, "emoji": emoji}


def board_snapshot(state: CombatState) -> dict:
    ensure_positions(state)
    template = template_for_state(state)
    active = state.active_combatant()
    moves: list[list[int]] = []
    threats: list[list[int]] = []
    allies: list[list[int]] = []
    if active is not None:
        moves = [list(cell) for cell in sorted(reachable_cells(state, active))]
        if not active.acted:
            for target in attack_targets_in_range(
                state, active, weapon_range_squares(active)
            ):
                if target.x is None or target.y is None:
                    continue
                cell = [target.x, target.y]
                if same_side(active, target):
                    allies.append(cell)
                else:
                    threats.append(cell)
    combatants: list[dict] = []
    for name in state.turn_order:
        combatant = state.combatants.get(name.lower())
        if combatant is None:
            continue
        pc = combatant.user_id is not None
        combatants.append(
            {
                "name": combatant.name,
                "initials": token_initials(combatant.name),
                "pc": pc,
                "x": combatant.x,
                "y": combatant.y,
                "hp": combatant.hp if pc else None,
                "max_hp": combatant.max_hp if pc else None,
                "down": _is_down(combatant),
                "active": name == state.active_name,
                "conditions": list(combatant.conditions),
                "cell": cell_label(combatant.x, combatant.y, state),
            }
        )
    return {
        "map": {
            "id": state.map_id,
            "label": template.label,
            "theme": template.theme,
            "width": map_width(state),
            "height": map_height(state),
            "blocked": [list(cell) for cell in sorted(state.blocked_set)],
        },
        "active": active.name if active is not None else None,
        "move_left": remaining_squares(active) if active is not None else 0,
        "move_total": speed_squares(active.speed) if active is not None else 0,
        "acted": bool(active.acted) if active is not None else True,
        "moves": moves,
        "threats": threats,
        "allies": allies,
        "hand": _public_hand(active),
        "combatants": combatants,
        "log": [_log_entry(line) for line in state.log[-8:]],
        "prefix": PREFIX,
    }


def _public_hand(active: CombatantState | None) -> list[dict]:
    if active is None:
        return []
    cards: list[dict] = []
    seen: set[str] = set()
    for card_id in list(active.hand) + list(active.card_catalog):
        if card_id in seen:
            continue
        card = lookup_card(active.card_catalog, card_id)
        if card is None:
            continue
        in_hand = card_id in active.hand
        if not in_hand and not is_spellbook_card(card):
            continue
        seen.add(card_id)
        cards.append(
            {
                "id": card.card_id,
                "label": card.label,
                "needs_target": bool(card.needs_target or card.aoe_radius),
                "target_enemies": bool(card.target_enemies_only),
                "target_allies": bool(card.target_allies_only),
                "aoe": bool(card.aoe_radius),
                "spell": not in_hand,
            }
        )
        if len(cards) >= 24:
            break
    return cards


def _parse_dest(raw: object, state: CombatState) -> tuple[int, int] | None:
    if isinstance(raw, str):
        return parse_cell(raw, state)
    if isinstance(raw, dict) and "x" in raw and "y" in raw:
        return int(raw["x"]), int(raw["y"])
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return int(raw[0]), int(raw[1])
    return None


async def apply_web_action(
    guild_id: int, scope_id: int, payload: dict
) -> dict:
    action = str(payload.get("type") or "").strip().lower()
    if action == "command":
        outcome = await run_web_command(
            guild_id, scope_id, str(payload.get("text") or "")
        )
        snapshot = (
            None
            if outcome.combat_over or outcome.state is None
            else board_snapshot(outcome.state)
        )
        if outcome.sync_discord or outcome.combat_over:
            sync_combat_message(
                outcome.state,
                content=_plain(outcome.message),
                ended=outcome.combat_over,
            )
        return {
            "ok": True,
            "message": _plain(outcome.message),
            "combat_over": outcome.combat_over,
            "snapshot": snapshot,
        }
    async with lock_for(guild_id=guild_id, scope_id=scope_id):
        state = get_combat(guild_id=guild_id, scope_id=scope_id)
        if state is None:
            raise ValueError("Aucun combat en cours.")
        active = state.active_combatant()
        if active is None:
            raise ValueError("Aucun combattant actif.")
        if action == "move":
            dest = _parse_dest(payload.get("dest"), state)
            if dest is None:
                raise ValueError("Case de destination inconnue.")
            result = move_combatant(
                state, actor_name=active.name, dest_x=dest[0], dest_y=dest[1]
            )
        elif action == "attack":
            target = str(payload.get("target") or "").strip()
            if not target:
                raise ValueError("Choisis une cible.")
            result = map_attack(
                state, actor_name=active.name, target_name=target
            )
        elif action == "play":
            card_id = str(payload.get("card") or "").strip()
            if not card_id:
                raise ValueError("Choisis une carte.")
            target = str(payload.get("target") or "").strip() or None
            result = play_card(
                state,
                actor_name=active.name,
                card_id=card_id,
                target_name=target,
            )
        elif action == "pass":
            result = finish_turn(state, actor_name=active.name)
        else:
            raise ValueError("Action inconnue.")
        snapshot = None if result.combat_over else board_snapshot(state)
    sync_combat_message(
        state,
        content=_plain(result.message),
        ended=result.combat_over,
    )
    return {
        "ok": True,
        "message": _plain(result.message),
        "combat_over": result.combat_over,
        "snapshot": snapshot,
    }
