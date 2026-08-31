import discord

from combat.cards import (
    CardSnapshot,
    card_description,
    is_spellbook_card,
    lookup_card,
)
from combat.editor_server import combat_board_url
from combat.map import cell_label, ensure_positions, remaining_squares, speed_squares
from combat.render import MAP_FILENAME, render_combat_map
from combat.storage import CombatState
from combat.templates import template_for_state
from combat.text import format_log_line
from combat.tokens import prefetch_monster_tokens


COMBAT_COLOR = 0x2B3038
BOARD_TITLE = "⚔️ Combat"


def format_hand(hand: list[str], catalog: dict[str, CardSnapshot]) -> str:
    if not hand:
        return "*(main vide)*"
    lines = []
    for card_id in hand:
        card = lookup_card(catalog, card_id)
        if card is None:
            lines.append(f"• `{card_id}`")
        else:
            lines.append(f"• {card_description(card)}")
    return "\n".join(lines)


def format_combat_log(state: CombatState) -> str:
    if not state.log:
        return "*(aucune action)*"
    return "\n".join(format_log_line(line) for line in state.log[-5:])


def _effect_label(combatant, effect_id: str) -> str:
    card = lookup_card(combatant.card_catalog, effect_id)
    return card.label if card else effect_id


def _hp_bar(current: int, maximum: int) -> str:
    if maximum <= 0:
        return ""
    ratio = max(0.0, min(1.0, current / maximum))
    filled = round(ratio * 6)
    return "▰" * filled + "▱" * (6 - filled)


def format_combatants(state: CombatState) -> str:
    lines: list[str] = []
    for name in state.turn_order:
        combatant = state.combatants.get(name.lower())
        if combatant is None:
            continue
        marker = "➤ " if name == state.active_name else "• "
        extras: list[str] = []
        if combatant.traits:
            extras.append(", ".join(combatant.traits))
        if combatant.effects:
            effect_labels = ", ".join(
                _effect_label(combatant, effect_id) for effect_id in combatant.effects
            )
            if effect_labels:
                extras.append(effect_labels)
        if combatant.user_id is not None and combatant.hp <= 0:
            if combatant.death_save_failures >= 3:
                extras.append("mort")
            elif combatant.death_save_successes >= 3:
                extras.append("stable")
            else:
                extras.append(
                    f"mourant {combatant.death_save_successes}R/{combatant.death_save_failures}E"
                )
        if combatant.x is not None and combatant.y is not None:
            extras.insert(0, cell_label(combatant.x, combatant.y, state))
        extra = f" · _{', '.join(extras)}_" if extras else ""
        if combatant.user_id is None:
            status = " 💀" if combatant.hp <= 0 else ""
            lines.append(f"{marker}**{combatant.name}**{extra}{status}")
        else:
            status = " 💀" if combatant.death_save_failures >= 3 else ""
            bar = _hp_bar(combatant.hp, combatant.max_hp)
            bar_part = f" `{bar}`" if bar else ""
            lines.append(
                f"{marker}**{combatant.name}** — ❤️ **{combatant.hp}/{combatant.max_hp}**"
                f"{bar_part}{extra}{status}"
            )
    return "\n".join(lines) if lines else "*(aucun combattant)*"


def build_combat_map_file(state: CombatState) -> discord.File:
    ensure_positions(state)
    prefetch_monster_tokens(state)
    return discord.File(render_combat_map(state), filename=MAP_FILENAME)


def board_attachments(state: CombatState) -> list[discord.File]:
    if combat_board_url(state.guild_id, state.scope_id):
        return []
    return [build_combat_map_file(state)]


def build_combat_embed(state: CombatState, *, ended: bool = False) -> discord.Embed:
    ensure_positions(state)
    active = state.active_combatant()
    title = BOARD_TITLE
    if ended:
        title = f"{BOARD_TITLE} — terminé"
    elif active is not None:
        title = f"{BOARD_TITLE} — tour de {active.name}"

    embed = discord.Embed(title=title, color=COMBAT_COLOR)
    details: list[str] = []
    if state.map_id and state.map_id != "arena":
        details.append(f"Carte : **{template_for_state(state).label}**")
    board_url = combat_board_url(state.guild_id, state.scope_id)
    if board_url:
        details.append(f"[Ouvrir le plateau]({board_url})")
    if details:
        embed.description = "\n".join(details)
    embed.add_field(name="📜 Actions", value=format_combat_log(state), inline=False)
    if board_url is None:
        embed.set_image(url=f"attachment://{MAP_FILENAME}")
    if ended:
        embed.set_footer(text="Combat terminé")
    elif active is not None:
        left = remaining_squares(active)
        total = speed_squares(active.speed)
        action = "faite" if active.acted else "prête"
        cell = cell_label(active.x, active.y, state)
        embed.set_footer(
            text=f"{active.name} · {cell} · {left}/{total} cases · joue dans le navigateur"
        )
    else:
        embed.set_footer(text="Joue sur le plateau navigateur")
    return embed


def format_spellbook(catalog: dict[str, CardSnapshot]) -> str:
    spells = [card for card in catalog.values() if is_spellbook_card(card)]
    if not spells:
        return ""
    spells.sort(key=lambda card: (card.spell_level, card.label.lower()))
    return "\n".join(f"• {card_description(card)}" for card in spells)


def build_hand_embed(
    *, combatant_name: str, hand: list[str], catalog: dict[str, CardSnapshot]
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🖐️ Main de {combatant_name}",
        description=format_hand(hand, catalog),
        color=COMBAT_COLOR,
    )
    spellbook = format_spellbook(catalog)
    if spellbook:
        if len(spellbook) > 1024:
            spellbook = spellbook[:1021] + "…"
        embed.add_field(name="📖 Grimoire", value=spellbook, inline=False)
    embed.set_footer(
        text="Tous tes sorts sont dans le menu. Une seule cible est choisie automatiquement."
    )
    return embed
