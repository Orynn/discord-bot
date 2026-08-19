import discord

from bot.messaging import send_interaction_message
from combat.cards import CardSnapshot, card_label, lookup_card
from combat.display import build_combat_embed, build_hand_embed
from combat.engine import end_turn, play_card, valid_targets
from combat.storage import CombatState, get_combat

COMBAT_SELECT_PREFIX = "arkann:combat:card:"
COMBAT_TARGET_PREFIX = "arkann:combat:target:"
COMBAT_END_TURN_PREFIX = "arkann:combat:end:"
COMBAT_HAND_PREFIX = "arkann:combat:hand:"


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


class CombatCardSelect(discord.ui.Select):
    def __init__(
        self,
        guild_id: int,
        hand: list[tuple[str, str, str]] | None = None,
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
            placeholder = "Play a card…"
        else:
            options = [discord.SelectOption(label="—", value="noop")]
            placeholder = "No combat active"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{COMBAT_SELECT_PREFIX}{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        card_id = self.values[0]
        if card_id == "noop":
            await interaction.response.defer()
            return

        state = get_combat(guild_id=self.guild_id)
        if state is None:
            await send_interaction_message(interaction, content="This combat has ended.", ephemeral=True)
            return

        active = state.active_combatant()
        if active is None:
            await send_interaction_message(interaction, content="No active combatant.", ephemeral=True)
            return

        if active.user_id is not None and interaction.user.id != active.user_id:
            await send_interaction_message(
                interaction,
                content=f"It is **{active.name}**'s turn.",
                ephemeral=True,
            )
            return

        if card_id not in active.hand:
            await send_interaction_message(interaction, content="That card is no longer in hand.", ephemeral=True)
            return

        card = lookup_card(active.card_catalog, card_id)
        if card is None:
            await send_interaction_message(interaction, content="Unknown card.", ephemeral=True)
            return

        if card.needs_target:
            targets = valid_targets(state, actor=active, card_id=card_id)
            if not targets:
                await send_interaction_message(interaction, content="No valid targets.", ephemeral=True)
                return
            view = CombatTargetView(
                guild_id=self.guild_id,
                actor_name=active.name,
                card_id=card_id,
                targets=[(combatant.name.lower(), combatant.name) for combatant in targets],
            )
            await send_interaction_message(
                interaction,
                content=f"Choose a target for **{card.label}**.",
                view=view,
                ephemeral=True,
                definition_menu=False,
            )
            return

        try:
            result = play_card(state, actor_name=active.name, card_id=card_id)
        except ValueError as exc:
            await send_interaction_message(interaction, content=str(exc), ephemeral=True)
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
        guild_id: int,
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
            custom_id=f"{COMBAT_TARGET_PREFIX}{guild_id}:{card_id}",
        )
        self.guild_id = guild_id
        self.actor_name = actor_name
        self.card_id = card_id

    async def callback(self, interaction: discord.Interaction) -> None:
        target_key = self.values[0]
        state = get_combat(guild_id=self.guild_id)
        if state is None:
            await send_interaction_message(interaction, content="This combat has ended.", ephemeral=True)
            return

        target = state.combatants.get(target_key)
        if target is None:
            await send_interaction_message(interaction, content="Target not found.", ephemeral=True)
            return

        try:
            result = play_card(
                state,
                actor_name=self.actor_name,
                card_id=self.card_id,
                target_name=target.name,
            )
        except ValueError as exc:
            await send_interaction_message(interaction, content=str(exc), ephemeral=True)
            return

        await interaction.response.defer()
        if interaction.message is not None:
            channel = interaction.message.channel
            board_message = None
            async for message in channel.history(limit=20):
                if message.author.bot and message.embeds:
                    embed = message.embeds[0]
                    if embed.title and embed.title.startswith("Card combat"):
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
        guild_id: int,
        actor_name: str,
        card_id: str,
        targets: list[tuple[str, str]],
    ) -> None:
        super().__init__(timeout=120)
        self.add_item(CombatTargetSelect(guild_id, actor_name, card_id, targets))


class CombatEndTurnButton(discord.ui.Button):
    def __init__(self, guild_id: int) -> None:
        super().__init__(
            label="End turn",
            emoji="⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{COMBAT_END_TURN_PREFIX}{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        state = get_combat(guild_id=self.guild_id)
        if state is None:
            await send_interaction_message(interaction, content="This combat has ended.", ephemeral=True)
            return

        active = state.active_combatant()
        if active is None:
            await send_interaction_message(interaction, content="No active combatant.", ephemeral=True)
            return

        if active.user_id is not None and interaction.user.id != active.user_id:
            await send_interaction_message(
                interaction,
                content=f"It is **{active.name}**'s turn.",
                ephemeral=True,
            )
            return

        try:
            result = end_turn(state, actor_name=active.name)
        except ValueError as exc:
            await send_interaction_message(interaction, content=str(exc), ephemeral=True)
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
    def __init__(self, guild_id: int) -> None:
        super().__init__(
            label="View hand",
            emoji="🖐️",
            style=discord.ButtonStyle.primary,
            custom_id=f"{COMBAT_HAND_PREFIX}{guild_id}",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction) -> None:
        state = get_combat(guild_id=self.guild_id)
        if state is None:
            await send_interaction_message(interaction, content="This combat has ended.", ephemeral=True)
            return

        combatant = next(
            (entry for entry in state.combatants.values() if entry.user_id == interaction.user.id),
            None,
        )
        if combatant is None:
            active = state.active_combatant()
            if active is None or active.user_id != interaction.user.id:
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
    def __init__(self, state: CombatState | None = None, guild_id: int | None = None) -> None:
        super().__init__(timeout=None)
        resolved_guild_id = guild_id if guild_id is not None else (state.guild_id if state else 0)
        active = state.active_combatant() if state else None
        hand_options = (
            build_hand_select_options(active.hand, active.card_catalog)
            if active is not None
            else []
        )
        self.add_item(CombatCardSelect(resolved_guild_id, hand_options or None))
        self.add_item(CombatEndTurnButton(resolved_guild_id))
        self.add_item(CombatHandButton(resolved_guild_id))


def build_combat_view(state: CombatState) -> CombatBoardView:
    return CombatBoardView(state)


class PersistentCombatCardSelect(CombatCardSelect):
    def __init__(self, guild_id: int) -> None:
        super().__init__(guild_id, hand=None)


class PersistentCombatBoardView(discord.ui.View):
    def __init__(self, guild_id: int) -> None:
        super().__init__(timeout=None)
        self.add_item(PersistentCombatCardSelect(guild_id))
        self.add_item(CombatEndTurnButton(guild_id))
        self.add_item(CombatHandButton(guild_id))


def register_combat_views(bot: discord.Client) -> None:
    bot.add_view(PersistentCombatBoardView(guild_id=0))
