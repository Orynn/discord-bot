import discord

from srd import fivetools
from srd.embeds import (
    armor_embed,
    background_embed,
    class_embed,
    condition_embed,
    feat_embed,
    item_embed,
    skill_embed,
    monster_embed,
    species_embed,
    spell_embed,
    weapon_embed,
)
from srd.glossary import GlossaryEntry

_KIND_GETTERS = {
    "spell": (lambda entry: fivetools.get_spell(slug=entry.slug), spell_embed),
    "species": (lambda entry: fivetools.get_species(slug=entry.slug), species_embed),
    "class": (lambda entry: fivetools.get_class(slug=entry.slug), class_embed),
    "background": (lambda entry: fivetools.get_background(slug=entry.slug), background_embed),
    "condition": (lambda entry: fivetools.get_condition(slug=entry.slug), condition_embed),
    "feat": (lambda entry: fivetools.get_feat(slug=entry.slug), feat_embed),
    "weapon": (lambda entry: fivetools.get_weapon(slug=entry.slug), weapon_embed),
    "armor": (lambda entry: fivetools.get_armor(slug=entry.slug), armor_embed),
    "item": (lambda entry: fivetools.get_item(slug=entry.slug), item_embed),
    "skill": (lambda entry: fivetools.get_skill(slug=entry.slug), skill_embed),
    "monster": (lambda entry: fivetools.get_monster(slug=entry.slug), monster_embed),
}


async def build_definition_embed(entry: GlossaryEntry) -> discord.Embed:
    if entry.kind == "subrace":
        return species_embed(await fivetools.get_species(slug=entry.parent_slug or entry.slug))

    if entry.kind == "subclass" and entry.parent_slug:
        char_class = await fivetools.get_class(slug=entry.parent_slug)
        subclass = fivetools.find_subclass(char_class=char_class, query=entry.name)
        return class_embed(char_class, subclass=subclass)

    pair = _KIND_GETTERS.get(entry.kind)
    if pair is None:
        raise fivetools.Open5eNotFoundError(f"No definition available for {entry.name}.")
    getter, embed_fn = pair
    return embed_fn(await getter(entry))


def _kind_label(kind: str) -> str:
    labels = {
        "spell": "Spell",
        "species": "Species",
        "subrace": "Subrace",
        "class": "Class",
        "subclass": "Subclass",
        "background": "Background",
        "condition": "Condition",
        "feat": "Feat",
        "weapon": "Weapon",
        "armor": "Armor",
        "item": "Item",
        "skill": "Skill",
        "monster": "Monster",
    }
    return labels.get(kind, kind.title())


class DefinitionSelect(discord.ui.Select):
    def __init__(self, entries: list[GlossaryEntry] | None = None) -> None:
        if entries:
            options = [
                discord.SelectOption(
                    label=entry.name[:100],
                    value=f"{entry.kind}|{entry.slug}|{entry.parent_slug or ''}|{entry.name}",
                    description=_kind_label(entry.kind)[:100],
                )
                for entry in entries[:25]
            ]
        else:
            options = [discord.SelectOption(label="—", value="noop")]

        super().__init__(
            placeholder="View definition…",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="arkann:definition",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from bot.messaging import send_interaction_message

        raw = self.values[0]
        if raw == "noop":
            await interaction.response.defer()
            return

        await interaction.response.defer(ephemeral=True)

        kind, slug, parent_slug, name = raw.split("|", 3)
        entry = GlossaryEntry(
            name=name,
            kind=kind,
            slug=slug,
            url="",
            parent_slug=parent_slug or None,
        )
        try:
            view = None
            if entry.kind == "class":
                from srd.class_view import class_lookup_message

                embed, view = class_lookup_message(await fivetools.get_class(slug=entry.slug))
            elif entry.kind == "subclass" and entry.parent_slug:
                from srd.class_view import class_lookup_message

                char_class = await fivetools.get_class(slug=entry.parent_slug)
                subclass = fivetools.find_subclass(char_class=char_class, query=entry.name)
                embed, view = class_lookup_message(char_class, subclass=subclass)
            else:
                embed = await build_definition_embed(entry=entry)
        except fivetools.Open5eError as exc:
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
                content="Could not load that definition.",
                ephemeral=True,
                definition_menu=False,
            )
            return

        await send_interaction_message(
            interaction,
            embed=embed,
            view=view,
            ephemeral=True,
            definition_menu=False,
        )


class DefinitionSelectView(discord.ui.View):
    def __init__(self, entries: list[GlossaryEntry] | None = None) -> None:
        super().__init__(timeout=None)
        self.add_item(DefinitionSelect(entries=entries))


def build_definition_view(entries: list[GlossaryEntry]) -> DefinitionSelectView | None:
    unique = {entry.name.lower(): entry for entry in entries}.values()
    sorted_entries = sorted(unique, key=lambda entry: entry.name.lower())
    if not sorted_entries:
        return None
    return DefinitionSelectView(list(sorted_entries))
