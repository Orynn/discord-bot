import discord

from combat.cards import CardSnapshot, card_description, card_label, lookup_card
from combat.storage import CombatState


COMBAT_COLOR = 0xC0392B


def _card_for(combatant, card_id: str) -> CardSnapshot | None:
    return lookup_card(combatant.card_catalog, card_id)


def format_hand(hand: list[str], catalog: dict[str, CardSnapshot]) -> str:
    if not hand:
        return "*(empty hand)*"
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
        return "*(no actions yet)*"
    return "\n".join(f"• {line}" for line in state.log[-5:])


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
        status = " 💀" if combatant.hp <= 0 else ""
        effects = ""
        if combatant.effects:
            effect_labels = ", ".join(_effect_label(combatant, effect_id) for effect_id in combatant.effects)
            if effect_labels:
                effects = f" · _{effect_labels}_"
        bar = _hp_bar(combatant.hp, combatant.max_hp)
        bar_part = f" `{bar}`" if bar else ""
        lines.append(
            f"{marker}**{combatant.name}** — ❤️ **{combatant.hp}/{combatant.max_hp}**"
            f"{bar_part}{effects}{status}"
        )
    return "\n".join(lines) if lines else "*(no combatants)*"


def build_combat_embed(state: CombatState) -> discord.Embed:
    active = state.active_combatant()
    title = "🃏 Card combat"
    if active is not None:
        title = f"🃏 Card combat — {active.name}'s turn"

    embed = discord.Embed(title=title, color=COMBAT_COLOR)
    embed.add_field(name="⚔️ Combatants", value=format_combatants(state), inline=False)
    embed.add_field(name="📜 Recent actions", value=format_combat_log(state), inline=False)
    if active is not None and active.hand:
        preview = ", ".join(
            card_label(card)
            for card_id in active.hand[:5]
            if (card := _card_for(active, card_id)) is not None
        )
        embed.set_footer(text=f"🖐️ {active.name}'s hand: {preview}")
    else:
        embed.set_footer(text="Decks come from character sheets and your 5etools export")
    return embed


def build_hand_embed(*, combatant_name: str, hand: list[str], catalog: dict[str, CardSnapshot]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🖐️ {combatant_name}'s hand",
        description=format_hand(hand, catalog),
        color=COMBAT_COLOR,
    )
    embed.set_footer(text="Cards come from your sheet and your 5etools export.")
    return embed
