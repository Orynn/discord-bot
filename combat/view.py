import discord

from bot.checks import is_staff_member
from bot.messaging import send_interaction_message
from bot.selects import fresh_component_id, replace_message_view
from combat.cards import (
    CardSnapshot,
    card_label,
    card_requires_target,
    is_spellbook_card,
    lookup_card,
)
from combat.display import build_combat_embed, build_hand_embed
from combat.engine import can_control_combatant, end_turn, play_card, valid_targets
from combat.scope import PLAYER_COMBAT_ONLY, scope_id_for_channel
from combat.storage import CombatState, get_combat, lock_for

COMBAT_SELECT_ID = "arkann:combat:card"
COMBAT_END_TURN_ID = "arkann:combat:end"
COMBAT_HAND_ID = "arkann:combat:hand"


def build_hand_select_options(
    hand: list[str],
    catalog: dict[str, CardSnapshot],
) -> list[tuple[str, str, str]]:
    """Build select options with unique values (Discord rejects duplicate option values)."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for card_id in hand:
        if lookup_card(catalog, card_id) is None:
            continue
        if card_id not in counts:
            order.append(card_id)
            counts[card_id] = 0
        counts[card_id] += 1

    options: list[tuple[str, str, str]] = []
    for card_id in order[:25]:
        card = lookup_card(catalog, card_id)
        if card is None:
            continue
        label = card_label(card)
        if counts[card_id] > 1:
            label = f"{label} ×{counts[card_id]}"
        options.append((card_id, label, card.description))
    return options


def build_play_select_options(
    hand: list[str],
    catalog: dict[str, CardSnapshot],
    *,
    page: int = 0,
) -> tuple[list[tuple[str, str, str]], int, int]:
    options = build_hand_select_options(hand, catalog)
    seen = {card_id for card_id, _, _ in options}
    extra: list[tuple[str, str, str]] = []
    for card_id, card in catalog.items():
        if card_id in seen or not is_spellbook_card(card):
            continue
        extra.append((card_id, card_label(card), card.description))
    extra.sort(key=lambda item: item[1].lower())
    slots = max(0, 25 - len(options))
    if not extra or slots == 0:
        return options[:25], 0, 1
    page_count = max(1, (len(extra) + slots - 1) // slots)
    page = max(0, min(int(page), page_count - 1))
    start = page * slots
    return options + extra[start : start + slots], page, page_count


def _guild_id(interaction: discord.Interaction) -> int | None:
    return interaction.guild_id


def _scope_id(interaction: discord.Interaction) -> int | None:
    return scope_id_for_channel(guild=interaction.guild, channel=interaction.channel)


def _turn_denied_message(active_name: str, *, npc: bool) -> str:
    if npc:
        return f"Only the DM or this player can play for **{active_name}**."
    return f"It is **{active_name}**'s turn."


def _can_play(
    interaction: discord.Interaction, combatant, *, scope_id: int | None
) -> bool:
    return can_control_combatant(
        combatant=combatant,
        user_id=interaction.user.id,
        is_admin=is_staff_member(interaction.guild, interaction.user),
        scope_id=scope_id,
    )


class CombatCardSelect(discord.ui.Select):
    def __init__(
        self,
        hand: list[tuple[str, str, str]] | None = None,
        *,
        page: int = 0,
        page_count: int = 1,
    ) -> None:
        if hand:
            options = [
                discord.SelectOption(
                    label=label[:100],
                    value=card_id,
                    description=description[:100],
                )
                for card_id, label, description in hand[:25]
            ]
            placeholder = "Play a card or spell…"
            if page_count > 1:
                placeholder = f"Play a card or spell… ({page + 1}/{page_count})"
        else:
            options = [discord.SelectOption(label="—", value="noop")]
            placeholder = "No combat active"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=COMBAT_SELECT_ID,
            id=fresh_component_id(),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        card_id = self.values[0]
        if card_id == "noop":
            await interaction.response.defer()
            return

        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Combat is only available in a server.",
                ephemeral=True,
            )
            return
        if scope_id is None:
            await send_interaction_message(
                interaction, content=PLAYER_COMBAT_ONLY, ephemeral=True
            )
            return

        async with lock_for(guild_id=guild_id, scope_id=scope_id):
            state = get_combat(guild_id=guild_id, scope_id=scope_id)
            if state is None:
                await send_interaction_message(
                    interaction, content="This combat has ended.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="No active combatant.", ephemeral=True
                )
                return

            if not _can_play(interaction, active, scope_id=scope_id):
                await send_interaction_message(
                    interaction,
                    content=_turn_denied_message(
                        active.name, npc=active.user_id is None
                    ),
                    ephemeral=True,
                )
                return

            card = lookup_card(active.card_catalog, card_id)
            if card is None:
                await send_interaction_message(
                    interaction, content="Unknown card.", ephemeral=True
                )
                return

            if card_id not in active.hand and not is_spellbook_card(card):
                await send_interaction_message(
                    interaction,
                    content="That card is no longer in hand.",
                    ephemeral=True,
                )
                return

            target_name: str | None = None
            if card_requires_target(card):
                targets = valid_targets(state, actor=active, card_id=card_id)
                if not targets:
                    await send_interaction_message(
                        interaction, content="No valid targets.", ephemeral=True
                    )
                    return
                if len(targets) == 1:
                    target_name = targets[0].name
                else:
                    view = CombatTargetView(
                        actor_name=active.name,
                        card_id=card_id,
                        targets=[
                            (combatant.name.lower(), combatant.name)
                            for combatant in targets
                        ],
                    )
                    await send_interaction_message(
                        interaction,
                        content=f"Choose a target for **{card.label}**.",
                        view=view,
                        ephemeral=True,
                        definition_menu=False,
                    )
                    await replace_message_view(interaction, build_combat_view(state))
                    return

            try:
                result = play_card(
                    state,
                    actor_name=active.name,
                    card_id=card_id,
                    target_name=target_name,
                )
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await send_interaction_message(
            interaction,
            content=result.message,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            edit=True,
            definition_menu=False,
        )


class CombatTargetSelect(discord.ui.Select):
    def __init__(
        self,
        actor_name: str,
        card_id: str,
        targets: list[tuple[str, str]],
    ) -> None:
        options = [
            discord.SelectOption(label=name[:100], value=key)
            for key, name in targets[:25]
        ]
        super().__init__(
            placeholder="Choose a target…",
            min_values=1,
            max_values=1,
            options=options,
            id=fresh_component_id(),
        )
        self.actor_name = actor_name
        self.card_id = card_id
        self.targets = targets

    async def callback(self, interaction: discord.Interaction) -> None:
        target_key = self.values[0]
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Combat is only available in a server.",
                ephemeral=True,
            )
            await _reset_target_select(interaction, self)
            return
        if scope_id is None:
            await send_interaction_message(
                interaction, content=PLAYER_COMBAT_ONLY, ephemeral=True
            )
            await _reset_target_select(interaction, self)
            return

        async with lock_for(guild_id=guild_id, scope_id=scope_id):
            state = get_combat(guild_id=guild_id, scope_id=scope_id)
            if state is None:
                await send_interaction_message(
                    interaction, content="This combat has ended.", ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

            actor = state.find_combatant(self.actor_name)
            if actor is None or not _can_play(interaction, actor, scope_id=scope_id):
                await send_interaction_message(
                    interaction, content="You cannot play that card.", ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

            target = state.combatants.get(target_key)
            if target is None:
                await send_interaction_message(
                    interaction, content="Target not found.", ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

            try:
                result = play_card(
                    state,
                    actor_name=self.actor_name,
                    card_id=self.card_id,
                    target_name=target.name,
                )
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

        await interaction.response.defer()
        if interaction.message is not None:
            channel = interaction.message.channel
            board_message = None
            async for message in channel.history(limit=20):
                if message.author.bot and message.embeds:
                    embed = message.embeds[0]
                    if embed.title and embed.title.startswith("🃏 Card combat"):
                        board_message = message
                        break
            if board_message is not None:
                await board_message.edit(
                    embed=build_combat_embed(state),
                    view=build_combat_view(state),
                )
        await interaction.followup.send(result.message, ephemeral=True)


class CombatTargetView(discord.ui.View):
    def __init__(
        self,
        actor_name: str,
        card_id: str,
        targets: list[tuple[str, str]],
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(CombatTargetSelect(actor_name, card_id, targets))


async def _reset_target_select(
    interaction: discord.Interaction, select: CombatTargetSelect
) -> None:
    await replace_message_view(
        interaction,
        CombatTargetView(select.actor_name, select.card_id, select.targets),
    )


class CombatSpellPageButton(discord.ui.Button):
    def __init__(self, *, delta: int, page: int, page_count: int) -> None:
        going_prev = delta < 0
        super().__init__(
            label="◀ Spells" if going_prev else "Spells ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(page + delta < 0) or (page + delta >= page_count),
            row=1,
            id=fresh_component_id(),
        )
        self.delta = delta
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Combat is only available in a server.",
                ephemeral=True,
            )
            return
        if scope_id is None:
            await send_interaction_message(
                interaction, content=PLAYER_COMBAT_ONLY, ephemeral=True
            )
            return

        state = get_combat(guild_id=guild_id, scope_id=scope_id)
        if state is None:
            await send_interaction_message(
                interaction, content="This combat has ended.", ephemeral=True
            )
            return

        await send_interaction_message(
            interaction,
            embed=build_combat_embed(state),
            view=CombatBoardView(state, spell_page=self.page + self.delta),
            edit=True,
            definition_menu=False,
        )


class CombatEndTurnButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="End turn",
            emoji="⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id=COMBAT_END_TURN_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Combat is only available in a server.",
                ephemeral=True,
            )
            return
        if scope_id is None:
            await send_interaction_message(
                interaction, content=PLAYER_COMBAT_ONLY, ephemeral=True
            )
            return

        async with lock_for(guild_id=guild_id, scope_id=scope_id):
            state = get_combat(guild_id=guild_id, scope_id=scope_id)
            if state is None:
                await send_interaction_message(
                    interaction, content="This combat has ended.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="No active combatant.", ephemeral=True
                )
                return

            if not _can_play(interaction, active, scope_id=scope_id):
                await send_interaction_message(
                    interaction,
                    content=_turn_denied_message(
                        active.name, npc=active.user_id is None
                    ),
                    ephemeral=True,
                )
                return

            try:
                result = end_turn(state, actor_name=active.name)
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await send_interaction_message(
            interaction,
            content=result.message,
            embed=build_combat_embed(state),
            view=build_combat_view(state),
            edit=True,
            definition_menu=False,
        )


class CombatHandButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="View hand",
            emoji="🖐️",
            style=discord.ButtonStyle.primary,
            custom_id=COMBAT_HAND_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Combat is only available in a server.",
                ephemeral=True,
            )
            return
        if scope_id is None:
            await send_interaction_message(
                interaction, content=PLAYER_COMBAT_ONLY, ephemeral=True
            )
            return

        state = get_combat(guild_id=guild_id, scope_id=scope_id)
        if state is None:
            await send_interaction_message(
                interaction, content="This combat has ended.", ephemeral=True
            )
            return

        combatant = next(
            (
                entry
                for entry in state.combatants.values()
                if entry.user_id == interaction.user.id
            ),
            None,
        )
        if combatant is None:
            active = state.active_combatant()
            if active is None or not _can_play(interaction, active, scope_id=scope_id):
                await send_interaction_message(
                    interaction,
                    content="You are not a combatant in this fight.",
                    ephemeral=True,
                )
                return
            combatant = active

        await send_interaction_message(
            interaction,
            embed=build_hand_embed(
                combatant_name=combatant.name,
                hand=combatant.hand,
                catalog=combatant.card_catalog,
            ),
            ephemeral=True,
            definition_menu=False,
        )


class CombatBoardView(discord.ui.View):
    def __init__(
        self, state: CombatState | None = None, *, spell_page: int = 0
    ) -> None:
        super().__init__(timeout=None)
        active = state.active_combatant() if state else None
        if active is not None:
            hand_options, page, page_count = build_play_select_options(
                active.hand,
                active.card_catalog,
                page=spell_page,
            )
        else:
            hand_options, page, page_count = [], 0, 1
        self.spell_page = page
        self.add_item(
            CombatCardSelect(hand_options or None, page=page, page_count=page_count)
        )
        if page_count > 1:
            self.add_item(
                CombatSpellPageButton(delta=-1, page=page, page_count=page_count)
            )
            self.add_item(
                CombatSpellPageButton(delta=1, page=page, page_count=page_count)
            )
        self.add_item(CombatEndTurnButton())
        self.add_item(CombatHandButton())


def build_combat_view(state: CombatState, *, spell_page: int = 0) -> CombatBoardView:
    return CombatBoardView(state, spell_page=spell_page)


class PersistentCombatBoardView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(CombatCardSelect())
        self.add_item(CombatEndTurnButton())
        self.add_item(CombatHandButton())


def register_combat_views(bot: discord.Client) -> None:
    bot.add_view(PersistentCombatBoardView())
