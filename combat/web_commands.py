import random
from dataclasses import dataclass

from combat.cards import lookup_card, resolve_card_id
from combat.custom_maps import (
    DEFAULT_MAP_HEIGHT,
    DEFAULT_MAP_WIDTH,
    THEMES,
    CustomMapData,
    custom_map_from_state,
    delete_custom_map,
    format_map_text,
    get_custom_map,
    list_custom_maps,
    parse_size_token,
    save_custom_map,
    slugify_map_id,
    validate_map_id,
)
from combat.engine import (
    add_combatant,
    attack_targets_in_weapon_range,
    finish_turn,
    map_attack,
    move_combatant,
    play_card,
    start_combat,
)
from combat.map import (
    apply_template,
    cell_label,
    ensure_positions,
    parse_cell,
    parse_destination,
    toggle_walls,
)
from combat.setup import ensure_section_fight, parse_start_args
from combat.storage import CombatState, clear_combat, get_combat, lock_for, save_combat
from combat.templates import TEMPLATES, lookup_template
from config import PREFIX
from initiative.display import advance_turn
from initiative.storage import (
    InitiativeState,
    add_initiative_entry,
    clear_initiative,
    get_initiative,
    save_initiative,
)
from sheets.dice import (
    execute_roll,
    format_roll_result,
    parse_roll_args,
    validate_roll_request,
)
from sheets.storage import get_sheet

COMBAT_VERBS = frozenset(
    {
        "move",
        "attack",
        "play",
        "pass",
        "hand",
        "add",
        "end",
        "map",
        "start",
        "board",
        "help",
        "menu",
    }
)
INIT_VERBS = frozenset({"show", "next", "add", "clear", "remove", "help"})


@dataclass(frozen=True)
class WebCommandOutcome:
    message: str
    state: CombatState | None = None
    combat_over: bool = False
    sync_discord: bool = False


def parse_web_command(text: str) -> tuple[str, str, list[str]]:
    raw = text.strip()
    if raw.startswith(PREFIX):
        raw = raw[len(PREFIX) :].strip()
    if raw.startswith("/"):
        raw = raw[1:].strip()
    if not raw:
        raise ValueError("Commande vide.")
    parts = raw.split()
    head = parts[0].lower()
    rest = parts[1:]
    if head in {"combat", "c"}:
        if not rest:
            return "combat", "help", []
        verb = rest[0].lower()
        if verb not in COMBAT_VERBS:
            raise ValueError(_unknown(text))
        return "combat", verb, rest[1:]
    if head in {"init", "initiative"}:
        if not rest:
            return "init", "show", []
        verb = rest[0].lower()
        if verb not in INIT_VERBS:
            raise ValueError(_unknown(text))
        return "init", verb, rest[1:]
    if head in {"r", "roll"}:
        return "roll", "roll", rest
    if head in {"help", "aide"}:
        topic = rest[0].lower() if rest else "combat"
        return "help", topic, rest[1:]
    if head in COMBAT_VERBS:
        return "combat", head, rest
    if head in {"next", "show"}:
        return "init", head, rest
    raise ValueError(_unknown(text))


def _unknown(text: str) -> str:
    return (
        f"Commande inconnue `{text.strip()}`. "
        f"Essaie `{PREFIX}combat help` ou `{PREFIX}r 1d20`."
    )


def command_help() -> str:
    return (
        f"`{PREFIX}combat move C4` · `{PREFIX}combat attack [cible]`\n"
        f"`{PREFIX}combat play <carte> [cible]` · `{PREFIX}combat pass`\n"
        f"`{PREFIX}combat hand` · `{PREFIX}combat add <nom> [pv]` · `{PREFIX}combat end`\n"
        f"`{PREFIX}combat map tavern` · `{PREFIX}combat map wall C3` · `{PREFIX}combat start`\n"
        f"`{PREFIX}init show` · `{PREFIX}init add Loup` · `{PREFIX}init next`\n"
        f"`{PREFIX}r 1d20` · `{PREFIX}r athletics` · `{PREFIX}help combat`\n"
        "Le `;` est optionnel ici. Même syntaxe qu’à Discord."
    )


async def run_web_command(
    guild_id: int, scope_id: int, text: str
) -> WebCommandOutcome:
    group, verb, args = parse_web_command(text)
    if group == "help":
        return WebCommandOutcome(
            message=command_help(),
            state=get_combat(guild_id=guild_id, scope_id=scope_id),
        )
    if group == "roll":
        return _run_roll(guild_id, scope_id, args)
    if group == "init":
        return _run_init(guild_id, scope_id, verb, args)
    return await _run_combat(guild_id, scope_id, verb, args)


def _run_roll(
    guild_id: int, scope_id: int, args: list[str]
) -> WebCommandOutcome:
    if not args:
        raise ValueError(
            f"Usage : `{PREFIX}r 1d20` · `{PREFIX}r athletics` · `{PREFIX}r adv dex save`."
        )
    state = get_combat(guild_id=guild_id, scope_id=scope_id)
    sheet = None
    label = "Jet"
    if state is not None:
        active = state.active_combatant()
        if active is not None and active.user_id is not None:
            sheet = get_sheet(user_id=active.user_id, guild_id=guild_id)
            label = active.name
        elif active is not None:
            label = active.name
    request = parse_roll_args(" ".join(args))
    validate_roll_request(request)
    result = execute_roll(
        dice=request.dice,
        sheet=sheet,
        modifier_tokens=request.modifier_tokens,
        advantage=request.advantage,
    )
    return WebCommandOutcome(
        message=format_roll_result(result, roller_label=label).replace("**", ""),
        state=state,
    )


def _run_init(
    guild_id: int, scope_id: int, verb: str, args: list[str]
) -> WebCommandOutcome:
    state = get_combat(guild_id=guild_id, scope_id=scope_id)
    if verb == "help":
        return WebCommandOutcome(
            message=(
                f"`{PREFIX}init add Loup` · `{PREFIX}init add Loup 2`\n"
                f"`{PREFIX}init show` · `{PREFIX}init next`\n"
                f"`{PREFIX}init remove Loup` · `{PREFIX}init clear`"
            ),
            state=state,
        )
    if verb == "show":
        initiative = get_initiative(guild_id=guild_id, scope_id=scope_id)
        if initiative is None or not initiative.order:
            raise ValueError("Pas d’initiative.")
        return WebCommandOutcome(message=_init_text(initiative), state=state)
    if verb == "next":
        result = advance_turn(guild_id=guild_id, scope_id=scope_id)
        if result is None:
            raise ValueError("Pas d’initiative.")
        initiative, current = result
        return WebCommandOutcome(
            message=f"Tour : {current.name}\n{_init_text(initiative)}",
            state=state,
        )
    if verb == "clear":
        clear_initiative(guild_id=guild_id, scope_id=scope_id)
        return WebCommandOutcome(message="Initiative effacée.", state=state)
    if verb == "remove":
        name = " ".join(args).strip()
        if not name:
            raise ValueError(f"Usage : `{PREFIX}init remove <nom>`.")
        initiative = get_initiative(guild_id=guild_id, scope_id=scope_id)
        if initiative is None or not initiative.order:
            raise ValueError("Pas d’initiative.")
        query = name.lower()
        initiative.order = [
            entry for entry in initiative.order if query not in entry.name.lower()
        ]
        if not initiative.order:
            clear_initiative(guild_id=guild_id, scope_id=scope_id)
        else:
            initiative.active_index = min(
                initiative.active_index, len(initiative.order) - 1
            )
            save_initiative(guild_id=guild_id, scope_id=scope_id, state=initiative)
        return WebCommandOutcome(message=f"{name} retiré de l’initiative.", state=state)
    if verb == "add":
        return _init_add(guild_id, scope_id, args, state)
    raise ValueError(_unknown(verb))


def _init_add(
    guild_id: int,
    scope_id: int,
    args: list[str],
    combat: CombatState | None,
) -> WebCommandOutcome:
    cleaned = " ".join(args).strip()
    if not cleaned:
        raise ValueError(f"Usage : `{PREFIX}init add <nom> [mod]`.")
    parts = cleaned.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].lstrip("+-").isdigit():
        entry_name, modifier = parts[0], int(parts[1])
    else:
        entry_name, modifier = cleaned, 0
    initiative = get_initiative(guild_id=guild_id, scope_id=scope_id)
    if initiative is None:
        channel_id = combat.channel_id if combat is not None else scope_id
        initiative = InitiativeState(
            channel_id=channel_id, active_index=0, order=[]
        )
    roll = random.randint(1, 20)
    total = roll + modifier
    add_initiative_entry(
        initiative, name=entry_name, total=total, user_id=None
    )
    save_initiative(guild_id=guild_id, scope_id=scope_id, state=initiative)
    sign = f"+{modifier}" if modifier >= 0 else str(modifier)
    return WebCommandOutcome(
        message=f"{entry_name} : {total} (d20 {roll} {sign})\n{_init_text(initiative)}",
        state=combat,
    )


def _init_text(initiative: InitiativeState) -> str:
    lines: list[str] = []
    for index, entry in enumerate(initiative.order):
        mark = "➤ " if index == initiative.active_index else ""
        lines.append(f"{mark}{entry.total} {entry.name}")
    return "\n".join(lines) or "Initiative vide."


async def _run_combat(
    guild_id: int, scope_id: int, verb: str, args: list[str]
) -> WebCommandOutcome:
    if verb in {"help", "menu"}:
        return WebCommandOutcome(
            message=command_help(),
            state=get_combat(guild_id=guild_id, scope_id=scope_id),
        )
    if verb == "start":
        return await _combat_start(guild_id, scope_id, args)

    async with lock_for(guild_id=guild_id, scope_id=scope_id):
        state = get_combat(guild_id=guild_id, scope_id=scope_id)
        if verb == "end":
            if state is not None:
                clear_combat(guild_id=guild_id, scope_id=scope_id)
            return WebCommandOutcome(
                message="Combat terminé.",
                state=state,
                combat_over=True,
                sync_discord=True,
            )
        if state is None:
            raise ValueError("Aucun combat en cours. Lance `;combat start` d’abord.")
        if verb == "board":
            return WebCommandOutcome(message="Plateau actualisé.", state=state)
        if verb == "hand":
            return WebCommandOutcome(message=_hand_text(state), state=state)
        if verb == "map":
            return _combat_map(guild_id, state, args)
        if verb == "add":
            return await _combat_add(state, args)
        active = state.active_combatant()
        if active is None:
            raise ValueError("Aucun combattant actif.")
        if verb == "pass":
            result = finish_turn(state, actor_name=active.name)
            return WebCommandOutcome(
                message=result.message,
                state=state,
                combat_over=result.combat_over,
                sync_discord=True,
            )
        if verb == "move":
            dest = " ".join(args).strip()
            if not dest:
                raise ValueError(
                    f"Usage : `{PREFIX}combat move C4` ou `{PREFIX}combat move 2e`."
                )
            ensure_positions(state)
            cell = parse_destination(active, dest, state)
            if cell is None:
                raise ValueError(
                    f"Destination inconnue `{dest}`. Utilise `C4` ou `2e` / `nord`."
                )
            result = move_combatant(
                state, actor_name=active.name, dest_x=cell[0], dest_y=cell[1]
            )
            return WebCommandOutcome(
                message=result.message,
                state=state,
                combat_over=result.combat_over,
                sync_discord=True,
            )
        if verb == "attack":
            target_name = " ".join(args).strip()
            if not target_name:
                nearby = attack_targets_in_weapon_range(state, active)
                if not nearby:
                    cell = cell_label(active.x, active.y, state)
                    raise ValueError(
                        f"Aucune cible à portée de {active.name} ({cell})."
                    )
                if len(nearby) > 1:
                    names = ", ".join(entry.name for entry in nearby)
                    raise ValueError(
                        f"Plusieurs cibles à portée : {names}. "
                        f"`{PREFIX}combat attack <nom>`"
                    )
                target_name = nearby[0].name
            result = map_attack(
                state, actor_name=active.name, target_name=target_name
            )
            return WebCommandOutcome(
                message=result.message,
                state=state,
                combat_over=result.combat_over,
                sync_discord=True,
            )
        if verb == "play":
            if not args:
                raise ValueError(
                    f"Usage : `{PREFIX}combat play <carte> [cible]`."
                )
            card_id = resolve_card_id(args[0], active.card_catalog)
            if card_id is None:
                labels = ", ".join(
                    sorted(card.label for card in active.card_catalog.values())
                )
                raise ValueError(f"Carte inconnue. Main : {labels}")
            target = " ".join(args[1:]).strip() or None
            result = play_card(
                state,
                actor_name=active.name,
                card_id=card_id,
                target_name=target,
            )
            return WebCommandOutcome(
                message=result.message,
                state=state,
                combat_over=result.combat_over,
                sync_discord=True,
            )
    raise ValueError(_unknown(verb))


async def _combat_start(
    guild_id: int, scope_id: int, args: list[str]
) -> WebCommandOutcome:
    monster_name, _minutes, map_id = parse_start_args(
        " ".join(args), guild_id=guild_id
    )
    existing = get_combat(guild_id=guild_id, scope_id=scope_id)
    channel_id = existing.channel_id if existing is not None else scope_id
    async with lock_for(guild_id=guild_id, scope_id=scope_id):
        await ensure_section_fight(
            guild_id=guild_id,
            channel_id=channel_id,
            scope_id=scope_id,
            player_id=None,
            monster_name=monster_name,
        )
        state = await start_combat(
            guild_id=guild_id,
            channel_id=channel_id,
            scope_id=scope_id,
            map_id=map_id,
        )
    return WebCommandOutcome(
        message=state.log[-1] if state.log else "Combat lancé.",
        state=state,
        sync_discord=True,
    )


async def _combat_add(state: CombatState, args: list[str]) -> WebCommandOutcome:
    cleaned = " ".join(args).strip()
    if not cleaned:
        raise ValueError(f"Usage : `{PREFIX}combat add <nom> [pv]`.")
    parts = cleaned.rsplit(maxsplit=1)
    if len(parts) == 2 and parts[1].isdigit():
        name, hp = parts[0], int(parts[1])
    else:
        name, hp = cleaned, None
    combatant = await add_combatant(state, name=name, hp=hp)
    traits = f" · {', '.join(combatant.traits)}" if combatant.traits else ""
    return WebCommandOutcome(
        message=f"{combatant.name} ajouté{traits} ({combatant.hp} PV).",
        state=state,
        sync_discord=True,
    )


def _combat_map(
    guild_id: int, state: CombatState, args: list[str]
) -> WebCommandOutcome:
    verb = args[0].lower() if args else "list"
    rest = args[1:]
    if verb in {"", "list"}:
        return WebCommandOutcome(message=_map_list(guild_id), state=state)
    if verb == "help":
        return WebCommandOutcome(
            message=(
                f"`{PREFIX}combat map tavern` · `{PREFIX}combat map wall C3 D4`\n"
                f"`{PREFIX}combat map save crypt` · `{PREFIX}combat map new crypt 12x12`\n"
                f"`{PREFIX}combat map show crypt` · `{PREFIX}combat map delete crypt`"
            ),
            state=state,
        )
    if verb == "editor":
        return WebCommandOutcome(
            message="Éditeur : ouvre /editor sur le même serveur que ce plateau.",
            state=state,
        )
    if verb == "wall":
        if not rest:
            raise ValueError(f"Usage : `{PREFIX}combat map wall C3 D4`.")
        cells: list[tuple[int, int]] = []
        for token in rest:
            cell = parse_cell(token, state)
            if cell is None:
                raise ValueError(f"Case inconnue `{token}`. Exemple : `C3`.")
            cells.append(cell)
        note = toggle_walls(state, cells)
        save_combat(state)
        return WebCommandOutcome(message=note, state=state, sync_discord=True)
    if verb == "save":
        map_id, label, theme = _parse_map_save(" ".join(rest))
        data = custom_map_from_state(state, map_id=map_id, label=label, theme=theme)
        save_custom_map(guild_id=guild_id, data=data)
        return WebCommandOutcome(
            message=f"Carte {data.label} enregistrée ({data.map_id}).",
            state=state,
        )
    if verb == "new":
        map_id, label, theme, size = _parse_map_new(" ".join(rest))
        width, height = size or (DEFAULT_MAP_WIDTH, DEFAULT_MAP_HEIGHT)
        data = CustomMapData(
            map_id=map_id,
            label=label or map_id.replace("-", " ").title(),
            blocked=(),
            theme=theme or "arena",
            width=width,
            height=height,
            npc_column=max(1, width - 2),
        )
        save_custom_map(guild_id=guild_id, data=data)
        return WebCommandOutcome(
            message=(
                f"Carte vide {data.label} ({data.map_id}). "
                f"`{PREFIX}combat map {data.map_id}` pour l’appliquer."
            ),
            state=state,
        )
    if verb == "show":
        raw = " ".join(rest).strip()
        if not raw:
            raise ValueError(f"Usage : `{PREFIX}combat map show crypt`.")
        data = _map_data(guild_id, raw)
        return WebCommandOutcome(
            message=f"{data.label} ({data.map_id})\n{format_map_text(data)}",
            state=state,
        )
    if verb in {"delete", "remove"}:
        raw = " ".join(rest).strip()
        if not raw:
            raise ValueError(f"Usage : `{PREFIX}combat map delete crypt`.")
        key = slugify_map_id(raw)
        if key in TEMPLATES:
            raise ValueError("Impossible de supprimer une carte de base.")
        if not delete_custom_map(guild_id=guild_id, map_id=key):
            raise ValueError(f"Carte perso `{key}` introuvable.")
        return WebCommandOutcome(message=f"Carte {key} supprimée.", state=state)
    if verb == "export":
        raw = " ".join(rest).strip()
        if not raw:
            raise ValueError(f"Usage : `{PREFIX}combat map export crypt`.")
        data = _map_data(guild_id, raw)
        return WebCommandOutcome(message=format_map_text(data), state=state)
    apply_template(state, verb)
    save_combat(state)
    label = lookup_template(state.map_id, guild_id=guild_id).label
    return WebCommandOutcome(
        message=f"Carte : {label}.",
        state=state,
        sync_discord=True,
    )


def _map_list(guild_id: int) -> str:
    built = " · ".join(f"{key} {item.label}" for key, item in TEMPLATES.items())
    customs = list_custom_maps(guild_id=guild_id)
    if customs:
        custom = "\n".join(
            f"• {entry.map_id} — {entry.label} ({entry.width}×{entry.height})"
            for entry in customs
        )
    else:
        custom = "(aucune carte perso)"
    return f"De base — {built}\nPerso\n{custom}"


def _map_data(guild_id: int, raw_id: str) -> CustomMapData:
    key = slugify_map_id(raw_id)
    if key in TEMPLATES:
        template = TEMPLATES[key]
        return CustomMapData(
            map_id=template.map_id,
            label=template.label,
            blocked=template.blocked,
            pc_column=template.pc_column,
            npc_column=template.npc_column,
            theme=template.theme,
            width=template.width,
            height=template.height,
        )
    data = get_custom_map(guild_id=guild_id, map_id=key)
    if data is None:
        raise ValueError(f"Carte inconnue `{raw_id}`.")
    return data


def _parse_map_save(text: str) -> tuple[str, str | None, str | None]:
    parts = text.split()
    if not parts:
        raise ValueError(f"Usage : `{PREFIX}combat map save crypt [nom] [dungeon]`.")
    map_id = validate_map_id(parts[0])
    if map_id in TEMPLATES:
        raise ValueError("Les cartes de base ne peuvent pas être écrasées.")
    theme = None
    label_parts: list[str] = []
    for part in parts[1:]:
        if parse_size_token(part) is not None:
            continue
        if part.lower() in THEMES and theme is None:
            theme = part.lower()
        else:
            label_parts.append(part)
    return map_id, " ".join(label_parts) or None, theme


def _parse_map_new(
    text: str,
) -> tuple[str, str | None, str | None, tuple[int, int] | None]:
    parts = text.split()
    if not parts:
        raise ValueError(
            f"Usage : `{PREFIX}combat map new crypt [nom] [12x12] [dungeon]`."
        )
    map_id = validate_map_id(parts[0])
    if map_id in TEMPLATES:
        raise ValueError("Les cartes de base ne peuvent pas être écrasées.")
    theme = None
    size = None
    label_parts: list[str] = []
    for part in parts[1:]:
        parsed = parse_size_token(part)
        if parsed is not None and size is None:
            size = parsed
        elif part.lower() in THEMES and theme is None:
            theme = part.lower()
        else:
            label_parts.append(part)
    return map_id, " ".join(label_parts) or None, theme, size


def _hand_text(state: CombatState) -> str:
    active = state.active_combatant()
    if active is None:
        return "Aucun combattant actif."
    labels: list[str] = []
    for card_id in active.hand:
        card = lookup_card(active.card_catalog, card_id)
        labels.append(card.label if card is not None else card_id)
    if not labels:
        return f"{active.name} n’a aucune carte en main."
    return f"Main de {active.name} : " + ", ".join(labels)
