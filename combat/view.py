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
from combat.display import (
    BOARD_TITLE,
    board_attachments,
    build_combat_embed,
    build_hand_embed,
)
from combat.editor_server import combat_board_url
from combat.engine import (
    can_control_combatant,
    conclude_if_over,
    attack_targets_in_weapon_range,
    finish_turn,
    map_attack,
    move_combatant,
    play_card,
    valid_targets,
)
from combat.map import DIRECTION_DELTA, ensure_positions
from combat.monster_sheet import (
    load_monster_sheet,
    npc_sheet_names,
    preferred_sheet_name,
)
from combat.scope import PLAYER_COMBAT_ONLY, scope_id_for_channel
from combat.storage import CombatState, get_combat, lock_for
from combat.text import play_in_browser

COMBAT_SELECT_ID = "arkann:combat:card"
COMBAT_END_TURN_ID = "arkann:combat:end"
COMBAT_HAND_ID = "arkann:combat:hand"
COMBAT_SHEET_ID = "arkann:combat:sheet"
COMBAT_MAP_ATTACK_ID = "arkann:combat:atk"
COMBAT_MOVE_IDS = {
    "w": "arkann:combat:w",
    "n": "arkann:combat:n",
    "s": "arkann:combat:s",
    "e": "arkann:combat:e",
}


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
        return f"Seul le MJ ou ce joueur peut jouer **{active_name}**."
    return f"C’est le tour de **{active_name}**."


def _can_play(
    interaction: discord.Interaction, combatant, *, scope_id: int | None
) -> bool:
    return can_control_combatant(
        combatant=combatant,
        user_id=interaction.user.id,
        is_admin=is_staff_member(interaction.guild, interaction.user),
        scope_id=scope_id,
    )


async def _reply_play_in_browser(interaction: discord.Interaction) -> None:
    guild_id = _guild_id(interaction)
    scope_id = _scope_id(interaction)
    url = (
        combat_board_url(guild_id, scope_id)
        if guild_id is not None and scope_id is not None
        else None
    )
    await send_interaction_message(
        interaction,
        content=play_in_browser(url),
        ephemeral=True,
        definition_menu=False,
    )


async def _edit_board(
    interaction: discord.Interaction,
    state: CombatState,
    *,
    content: str | None = None,
    combat_over: bool = False,
) -> None:
    ended = combat_over
    if not ended:
        victory = conclude_if_over(state)
        if victory is not None:
            ended = True
            content = (
                f"{content}\n{victory.message}" if content else victory.message
            )
    await send_interaction_message(
        interaction,
        content=content,
        embed=build_combat_embed(state, ended=ended),
        view=None if ended else build_combat_view(state),
        attachments=board_attachments(state),
        edit=True,
        definition_menu=False,
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
            placeholder = "Jouer une carte ou un sort…"
            if page_count > 1:
                placeholder = f"Jouer une carte ou un sort… ({page + 1}/{page_count})"
        else:
            options = [discord.SelectOption(label="—", value="noop")]
            placeholder = "Aucun combat"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=COMBAT_SELECT_ID,
            id=fresh_component_id(),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        card_id = self.values[0]
        if card_id == "noop":
            await interaction.response.defer()
            return

        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="Aucun combattant actif.", ephemeral=True
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
                    interaction, content="Carte inconnue.", ephemeral=True
                )
                return

            if card_id not in active.hand and not is_spellbook_card(card):
                await send_interaction_message(
                    interaction,
                    content="Cette carte n’est plus en main.",
                    ephemeral=True,
                )
                return

            target_name: str | None = None
            if card_requires_target(card):
                targets = valid_targets(state, actor=active, card_id=card_id)
                if not targets:
                    await send_interaction_message(
                        interaction, content="Aucune cible valide.", ephemeral=True
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
                        content=f"Choisis une cible pour **{card.label}**.",
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

        await _edit_board(
            interaction,
            state,
            content=result.message,
            combat_over=result.combat_over,
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
            placeholder="Choisis une cible…",
            min_values=1,
            max_values=1,
            options=options,
            id=fresh_component_id(),
        )
        self.actor_name = actor_name
        self.card_id = card_id
        self.targets = targets

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        target_key = self.values[0]
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

            actor = state.find_combatant(self.actor_name)
            if actor is None or not _can_play(interaction, actor, scope_id=scope_id):
                await send_interaction_message(
                    interaction, content="Tu ne peux pas jouer cette carte.", ephemeral=True
                )
                await _reset_target_select(interaction, self)
                return

            target = state.combatants.get(target_key)
            if target is None:
                await send_interaction_message(
                    interaction, content="Cible introuvable.", ephemeral=True
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
                    if embed.title and embed.title.startswith(BOARD_TITLE):
                        board_message = message
                        break
            if board_message is not None:
                await board_message.edit(
                    embed=build_combat_embed(state, ended=result.combat_over),
                    view=(
                        None
                        if result.combat_over
                        else build_combat_view(state)
                    ),
                    attachments=board_attachments(state),
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
            label="◀ Sorts" if going_prev else "Sorts ▶",
            style=discord.ButtonStyle.secondary,
            disabled=(page + delta < 0) or (page + delta >= page_count),
            row=1,
            id=fresh_component_id(),
        )
        self.delta = delta
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                interaction, content="Ce combat est terminé.", ephemeral=True
            )
            return

        await send_interaction_message(
            interaction,
            embed=build_combat_embed(state),
            view=CombatBoardView(state, spell_page=self.page + self.delta),
            attachments=board_attachments(state),
            edit=True,
            definition_menu=False,
        )


class CombatEndTurnButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Fin du tour",
            emoji="⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id=COMBAT_END_TURN_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="Aucun combattant actif.", ephemeral=True
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
                result = finish_turn(state, actor_name=active.name)
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await _edit_board(
            interaction,
            state,
            content=result.message,
            combat_over=result.combat_over,
        )


class CombatMoveButton(discord.ui.Button):
    def __init__(self, direction: str) -> None:
        labels = {"n": "▲", "s": "▼", "w": "◀", "e": "▶"}
        super().__init__(
            label=labels[direction],
            style=discord.ButtonStyle.secondary,
            custom_id=COMBAT_MOVE_IDS[direction],
            row=2,
        )
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="Aucun combattant actif.", ephemeral=True
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

            ensure_positions(state)
            if active.x is None or active.y is None:
                await send_interaction_message(
                    interaction,
                    content=f"**{active.name}** n’a pas de position sur la carte.",
                    ephemeral=True,
                )
                return
            dx, dy = DIRECTION_DELTA[self.direction]
            try:
                result = move_combatant(
                    state,
                    actor_name=active.name,
                    dest_x=active.x + dx,
                    dest_y=active.y + dy,
                )
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await _edit_board(
            interaction,
            state,
            content=result.message,
            combat_over=result.combat_over,
        )


class CombatMapAttackButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Attaquer",
            emoji="⚔️",
            style=discord.ButtonStyle.danger,
            custom_id=COMBAT_MAP_ATTACK_ID,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                return

            active = state.active_combatant()
            if active is None:
                await send_interaction_message(
                    interaction, content="Aucun combattant actif.", ephemeral=True
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

            targets = attack_targets_in_weapon_range(state, active)
            if not targets:
                await send_interaction_message(
                    interaction,
                    content="Aucune cible à portée d’arme. Approche-toi d’abord.",
                    ephemeral=True,
                )
                return
            if len(targets) > 1:
                view = CombatMapTargetView(
                    actor_name=active.name,
                    targets=[
                        (combatant.name.lower(), combatant.name)
                        for combatant in targets
                    ],
                )
                await send_interaction_message(
                    interaction,
                    content="Choisis qui attaquer.",
                    view=view,
                    ephemeral=True,
                    definition_menu=False,
                )
                return

            try:
                result = map_attack(
                    state, actor_name=active.name, target_name=targets[0].name
                )
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await _edit_board(
            interaction,
            state,
            content=result.message,
            combat_over=result.combat_over,
        )


class CombatMapTargetSelect(discord.ui.Select):
    def __init__(self, actor_name: str, targets: list[tuple[str, str]]) -> None:
        options = [
            discord.SelectOption(label=name[:100], value=key)
            for key, name in targets[:25]
        ]
        super().__init__(
            placeholder="Attaquer…",
            min_values=1,
            max_values=1,
            options=options,
            id=fresh_component_id(),
        )
        self.actor_name = actor_name
        self.targets = targets

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        target_key = self.values[0]
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None or scope_id is None:
            await send_interaction_message(
                interaction, content="Le combat n’est pas disponible ici.", ephemeral=True
            )
            return

        async with lock_for(guild_id=guild_id, scope_id=scope_id):
            state = get_combat(guild_id=guild_id, scope_id=scope_id)
            if state is None:
                await send_interaction_message(
                    interaction, content="Ce combat est terminé.", ephemeral=True
                )
                return
            actor = state.find_combatant(self.actor_name)
            if actor is None or not _can_play(interaction, actor, scope_id=scope_id):
                await send_interaction_message(
                    interaction, content="Tu ne peux pas attaquer maintenant.", ephemeral=True
                )
                return
            target = state.combatants.get(target_key)
            if target is None:
                await send_interaction_message(
                    interaction, content="Cible introuvable.", ephemeral=True
                )
                return
            try:
                result = map_attack(
                    state, actor_name=self.actor_name, target_name=target.name
                )
            except ValueError as exc:
                await send_interaction_message(
                    interaction, content=str(exc), ephemeral=True
                )
                return

        await interaction.response.defer()
        if interaction.message is not None:
            channel = interaction.channel
            if channel is not None and hasattr(channel, "history"):
                board_message = None
                async for message in channel.history(limit=20):
                    if message.author.bot and message.embeds:
                        embed = message.embeds[0]
                        if embed.title and embed.title.startswith(BOARD_TITLE):
                            board_message = message
                            break
                if board_message is not None:
                    await board_message.edit(
                        embed=build_combat_embed(
                            state, ended=result.combat_over
                        ),
                        view=(
                            None
                            if result.combat_over
                            else build_combat_view(state)
                        ),
                        attachments=board_attachments(state),
                    )
        await interaction.followup.send(result.message, ephemeral=True)


class CombatMapTargetView(discord.ui.View):
    def __init__(self, actor_name: str, targets: list[tuple[str, str]]) -> None:
        super().__init__(timeout=120)
        self.add_item(CombatMapTargetSelect(actor_name, targets))


class CombatHandButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Main",
            emoji="🖐️",
            style=discord.ButtonStyle.primary,
            custom_id=COMBAT_HAND_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _reply_play_in_browser(interaction)
        return
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                interaction, content="Ce combat est terminé.", ephemeral=True
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
                    content="Tu n’es pas dans ce combat.",
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


async def _send_monster_sheet(
    interaction: discord.Interaction, query: str, *, edit: bool = False
) -> None:
    embed, picker, error = await load_monster_sheet(query)
    if error is not None:
        await send_interaction_message(
            interaction,
            content=error,
            ephemeral=True,
            edit=edit,
            definition_menu=False,
        )
        return
    await send_interaction_message(
        interaction,
        embed=embed,
        view=picker,
        ephemeral=True,
        edit=edit,
        definition_menu=picker is None,
    )


class CombatMonsterSheetSelect(discord.ui.Select):
    def __init__(self, names: list[str]) -> None:
        options = [
            discord.SelectOption(label=name[:100], value=name[:100])
            for name in names[:25]
        ]
        super().__init__(
            placeholder="Fiche de monstre…",
            min_values=1,
            max_values=1,
            options=options,
            id=fresh_component_id(),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _send_monster_sheet(interaction, self.values[0], edit=True)


class CombatMonsterSheetView(discord.ui.View):
    def __init__(self, names: list[str]) -> None:
        super().__init__(timeout=120)
        self.add_item(CombatMonsterSheetSelect(names))


class CombatSheetButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Fiche",
            emoji="📖",
            style=discord.ButtonStyle.secondary,
            custom_id=COMBAT_SHEET_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild_id = _guild_id(interaction)
        scope_id = _scope_id(interaction)
        if guild_id is None:
            await send_interaction_message(
                interaction,
                content="Le combat n’est disponible que sur un serveur.",
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
                interaction, content="Ce combat est terminé.", ephemeral=True
            )
            return

        names = npc_sheet_names(state)
        if not names:
            await send_interaction_message(
                interaction,
                content="Aucun monstre dans ce combat.",
                ephemeral=True,
            )
            return

        chosen = preferred_sheet_name(state)
        if chosen is None:
            await send_interaction_message(
                interaction,
                content="Choisis un monstre.",
                view=CombatMonsterSheetView(names),
                ephemeral=True,
                definition_menu=False,
            )
            return

        await _send_monster_sheet(interaction, chosen)


class CombatBoardView(discord.ui.View):
    def __init__(
        self, state: CombatState | None = None, *, spell_page: int = 0
    ) -> None:
        super().__init__(timeout=None)
        self.spell_page = spell_page
        if state is not None:
            board_url = combat_board_url(state.guild_id, state.scope_id)
            if board_url:
                self.add_item(
                    discord.ui.Button(
                        label="Ouvrir le plateau",
                        style=discord.ButtonStyle.link,
                        url=board_url,
                    )
                )
        self.add_item(CombatSheetButton())


def build_combat_view(state: CombatState, *, spell_page: int = 0) -> CombatBoardView:
    return CombatBoardView(state, spell_page=spell_page)


class PersistentCombatBoardView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(CombatCardSelect())
        self.add_item(CombatEndTurnButton())
        self.add_item(CombatHandButton())
        self.add_item(CombatSheetButton())
        for direction in ("w", "n", "s", "e"):
            self.add_item(CombatMoveButton(direction))
        self.add_item(CombatMapAttackButton())


def register_combat_views(bot: discord.Client) -> None:
    bot.add_view(PersistentCombatBoardView())
