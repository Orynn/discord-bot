from __future__ import annotations

import discord

from bot.help_text import HelpSection, build_help_embed
from bot.messaging import prepare_outgoing


class HelpSectionButton(discord.ui.Button):
    def __init__(self, *, section_index: int, section: HelpSection, selected: bool) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary if selected else discord.ButtonStyle.secondary,
            emoji=section.emoji,
            label=section.button_label or section.label,
            row=0 if section_index < 5 else 1,
        )
        self.section_index = section_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView):
            await interaction.response.defer()
            return
        await view.select_section(interaction, self.section_index)


class HelpView(discord.ui.View):
    def __init__(
        self,
        *,
        title: str,
        sections: list[HelpSection],
        index: int = 0,
        timeout: float = 300,
    ) -> None:
        super().__init__(timeout=timeout)
        self.title = title
        self.sections = sections
        self.index = max(0, min(index, len(sections) - 1))
        self.message: discord.Message | None = None
        self._rebuild_buttons()

    def current_embed(self) -> discord.Embed:
        return build_help_embed(
            title=self.title,
            sections=self.sections,
            index=self.index,
        )

    def _rebuild_buttons(self) -> None:
        self.clear_items()
        for index, section in enumerate(self.sections):
            self.add_item(
                HelpSectionButton(
                    section_index=index,
                    section=section,
                    selected=index == self.index,
                )
            )

    async def select_section(
        self,
        interaction: discord.Interaction,
        section_index: int,
    ) -> None:
        if section_index == self.index:
            await interaction.response.defer()
            return
        self.index = section_index
        self._rebuild_buttons()
        _, prepared_embed, _, _ = prepare_outgoing(
            embed=self.current_embed(),
            definition_menu=False,
        )
        await interaction.response.edit_message(embed=prepared_embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
