import discord

from bot.help_text import HELP_INIT_COLOR
from initiative.storage import InitiativeEntry, InitiativeState, get_initiative, save_initiative


def format_initiative(state: InitiativeState) -> str:
    lines = []
    for index, entry in enumerate(state.order):
        marker = "➤ " if index == state.active_index else "• "
        lines.append(f"{marker}**{index + 1}.** **{entry.name}** — **{entry.total}**")
    return "\n".join(lines)


def build_initiative_embed(
    state: InitiativeState,
    *,
    notice: str | None = None,
) -> discord.Embed:
    active = None
    if state.order and 0 <= state.active_index < len(state.order):
        active = state.order[state.active_index]
    title = "⚡ Initiative"
    if active is not None:
        title = f"⚡ Initiative — {active.name}'s turn"
    embed = discord.Embed(title=title, description=notice, color=HELP_INIT_COLOR)
    embed.add_field(name="Turn order", value=format_initiative(state) or "—", inline=False)
    return embed


def advance_turn(*, guild_id: int, scope_id: int) -> tuple[InitiativeState, InitiativeEntry] | None:
    state = get_initiative(guild_id=guild_id, scope_id=scope_id)
    if not state or not state.order:
        return None
    state.active_index = (state.active_index + 1) % len(state.order)
    save_initiative(guild_id=guild_id, scope_id=scope_id, state=state)
    return state, state.order[state.active_index]
