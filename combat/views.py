"""Buttons and menus under the combat tracker, for playing from a phone.

The view is persistent (fixed custom ids, registered at startup): callbacks
read the encounter from the channel, so they keep working after a restart.
"""

from typing import Any

import discord

from combat.encounter import Encounter, load_encounter

NEXT_ID = "arkann:combat:next"
ATTACK_ID = "arkann:combat:attack"
CAST_ID = "arkann:combat:cast"
DEATH_ID = "arkann:combat:death"
MJ_ID = "arkann:combat:mj"
_MAX_OPTIONS = 25


class ComponentContext:
    """Just enough of `commands.Context` for the combat handlers."""

    is_component = True

    def __init__(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.author = interaction.user
        self.message = None

    async def send(
        self,
        content: str | None = None,
        *,
        ephemeral: bool = False,
        **kwargs: Any,
    ) -> discord.Message | None:
        payload = {key: value for key, value in kwargs.items() if value is not None}
        if content is not None:
            payload["content"] = content
        response = self.interaction.response
        if not response.is_done():
            await response.send_message(ephemeral=ephemeral, **payload)
            return await self.interaction.original_response()
        return await self.interaction.followup.send(
            ephemeral=ephemeral, wait=True, **payload
        )


def _encounter_for(interaction: discord.Interaction) -> Encounter | None:
    if interaction.guild is None or interaction.channel is None:
        return None
    return load_encounter(
        guild_id=interaction.guild.id, channel_id=interaction.channel.id
    )


class AttackSelect(discord.ui.Select):
    def __init__(self, encounter: Encounter | None) -> None:
        options = [
            discord.SelectOption(label=combatant.name[:100], value=combatant.id)
            for combatant in (encounter.order() if encounter else [])
            if not combatant.is_out
        ][:_MAX_OPTIONS] or [discord.SelectOption(label="—", value="none")]
        super().__init__(
            placeholder="⚔️ Attaquer…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=ATTACK_ID,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from combat.commands import handle_attack

        encounter = _encounter_for(interaction)
        target = encounter.get(self.values[0]) if encounter else None
        if target is None:
            await interaction.response.send_message(
                "Cette cible n’est plus dans le combat.", ephemeral=True
            )
            return
        await handle_attack(ComponentContext(interaction), target.name)


class SpellModal(discord.ui.Modal, title="Lancer un sort"):
    spell = discord.ui.TextInput(
        label="Sort", placeholder="boule de feu, fireball, fire breath…", max_length=100
    )
    targets = discord.ui.TextInput(
        label="Cibles (séparées par des virgules)",
        placeholder="gobelin 1, gobelin 2 — vide pour un soin sur toi",
        required=False,
        max_length=300,
    )
    options = discord.ui.TextInput(
        label="Options (facultatif)",
        placeholder="niv 4 · dc 15 · adv",
        required=False,
        max_length=60,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        from combat.commands import handle_cast

        args = f"{self.spell.value} {self.options.value}".strip()
        if self.targets.value.strip():
            args += f" sur {self.targets.value.strip()}"
        await handle_cast(ComponentContext(interaction), args)


class TrackerView(discord.ui.View):
    def __init__(self, encounter: Encounter | None = None) -> None:
        super().__init__(timeout=None)
        self.add_item(AttackSelect(encounter))

    @discord.ui.button(
        label="Tour suivant",
        emoji="⏭️",
        style=discord.ButtonStyle.primary,
        custom_id=NEXT_ID,
        row=0,
    )
    async def next_turn(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        from combat.commands import handle_next

        await handle_next(ComponentContext(interaction))

    @discord.ui.button(
        label="Sort",
        emoji="✨",
        style=discord.ButtonStyle.secondary,
        custom_id=CAST_ID,
        row=0,
    )
    async def cast(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(SpellModal())

    @discord.ui.button(
        label="Jet contre la mort",
        emoji="💀",
        style=discord.ButtonStyle.secondary,
        custom_id=DEATH_ID,
        row=0,
    )
    async def death_save(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        from combat.commands import handle_death_save

        await handle_death_save(ComponentContext(interaction), "")

    @discord.ui.button(
        label="Vue MJ",
        emoji="🧾",
        style=discord.ButtonStyle.secondary,
        custom_id=MJ_ID,
        row=0,
    )
    async def mj_view(
        self, interaction: discord.Interaction, _button: discord.ui.Button
    ) -> None:
        from combat.commands import handle_mj

        await handle_mj(ComponentContext(interaction))
