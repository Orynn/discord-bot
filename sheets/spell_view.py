import discord
from urllib.parse import quote, unquote

from bot.messaging import send_interaction_message
from srd import fivetools
from srd.embeds import kind_embed_color, spell_embed, titled
from srd.fivetools import entry_url
from srd.linkify import markdown_link
from srd.spell_slugs import HOMEBREW_PREFIX

SPELL_SELECT_PREFIX = "arkann:spell:"


def homebrew_slug(name: str) -> str:
    return f"{HOMEBREW_PREFIX}{quote(name.strip())}"


def is_homebrew_slug(slug: str) -> bool:
    return slug.startswith(HOMEBREW_PREFIX)


def homebrew_name_from_slug(slug: str) -> str:
    return unquote(slug[len(HOMEBREW_PREFIX) :])


class PersistentSpellSelect(discord.ui.Select):
    def __init__(self, chunk_index: int, spell_entries: list[tuple[str, str, str]] | None = None) -> None:
        if spell_entries:
            placeholder = (
                "Choose a spell…"
                if chunk_index == 0
                else f"Spells {chunk_index + 1}"
            )
            options = [
                discord.SelectOption(
                    label=name[:100],
                    value=slug,
                    description=(level or "Spell")[:100],
                )
                for slug, name, level in spell_entries[:25]
            ]
        else:
            placeholder = "Choose a spell…"
            options = [discord.SelectOption(label="—", value="noop")]

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"{SPELL_SELECT_PREFIX}{chunk_index}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        slug = self.values[0]
        if slug == "noop":
            await interaction.response.defer()
            return

        await interaction.response.defer(ephemeral=True)

        if is_homebrew_slug(slug):
            name = homebrew_name_from_slug(slug)
            embed = discord.Embed(
                title=titled("spell", name),
                description="Homebrew spell (not in the SRD).",
                color=kind_embed_color("spell_list"),
            )
            await send_interaction_message(
                interaction,
                embed=embed,
                ephemeral=True,
                definition_menu=False,
            )
            return
        try:
            spell = await fivetools.get_spell(slug=slug)
        except fivetools.FiveToolsError as exc:
            await send_interaction_message(
                interaction,
                content=str(exc),
                ephemeral=True,
                definition_menu=False,
            )
            return
        except Exception:
            await send_interaction_message(
                interaction,
                content="Could not load that spell.",
                ephemeral=True,
                definition_menu=False,
            )
            return
        await send_interaction_message(
            interaction,
            embed=spell_embed(spell),
            ephemeral=True,
            definition_menu=False,
        )


class SpellSelectView(discord.ui.View):
    def __init__(self, spell_entries: list[tuple[str, str, str]] | None = None) -> None:
        super().__init__(timeout=None)
        if spell_entries:
            sorted_entries = sorted(spell_entries, key=lambda entry: entry[1].lower())
            chunks = [sorted_entries[index : index + 25] for index in range(0, len(sorted_entries), 25)]
            for index, chunk in enumerate(chunks[:5]):
                self.add_item(PersistentSpellSelect(index, chunk))
        else:
            for index in range(5):
                self.add_item(PersistentSpellSelect(index))


def format_spell_lines(spell_entries: list[tuple[str, str, str]]) -> str:
    lines: list[str] = []
    for slug, name, level in sorted(spell_entries, key=lambda entry: entry[1].lower()):
        level_part = f" — {level}" if level else ""
        if is_homebrew_slug(slug):
            lines.append(f"**{name}**{level_part} *(homebrew)*")
        else:
            lines.append(f"{markdown_link(name, entry_url('spell', name))}{level_part}")
    return "\n".join(lines)


def build_spell_list_embed(*, title: str, spell_entries: list[tuple[str, str, str]]) -> discord.Embed:
    description = format_spell_lines(spell_entries)
    if len(description) > 4096:
        description = f"{description[:4093]}..."

    embed = discord.Embed(
        title=titled("spell_list", title),
        description=description or "No spells.",
        color=kind_embed_color("spell_list"),
    )
    embed.set_footer(text="Select a spell below to view SRD details.")
    return embed


def build_sheet_spell_view(spell_entries: list[tuple[str, str, str]]) -> SpellSelectView | None:
    if not spell_entries:
        return None
    return SpellSelectView(spell_entries)
