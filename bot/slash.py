import discord
from discord import app_commands
from discord.ext.commands.bot import Bot

from bot.messaging import send_interaction_message
from srd import fivetools
from srd.class_view import class_lookup_message
from srd.embeds import (
    armor_embed,
    background_embed,
    class_embed,
    condition_embed,
    feat_embed,
    item_embed,
    monster_embed,
    species_embed,
    spell_embed,
    weapon_embed,
)

SRD_LOOKUPS = {
    "spell": (fivetools.search_spell, spell_embed),
    "species": (fivetools.search_species, species_embed),
    "class": (fivetools.search_class, class_embed),
    "background": (fivetools.search_background, background_embed),
    "feat": (fivetools.search_feat, feat_embed),
    "condition": (fivetools.search_condition, condition_embed),
    "monster": (fivetools.search_monster, monster_embed),
    "weapon": (fivetools.search_weapon, weapon_embed),
    "armor": (fivetools.search_armor, armor_embed),
    "item": (fivetools.search_item, item_embed),
}

SRD_TYPE_CHOICES = [
    app_commands.Choice(name=label, value=value)
    for label, value in (
        ("Spell", "spell"),
        ("Species", "species"),
        ("Class", "class"),
        ("Background", "background"),
        ("Feat", "feat"),
        ("Condition", "condition"),
        ("Monster", "monster"),
        ("Weapon", "weapon"),
        ("Armor", "armor"),
        ("Item", "item"),
    )
]


def setup_slash(bot: Bot) -> None:
    @bot.tree.command(name="srd", description="Look up rules content from your 5etools export")
    @app_commands.describe(content_type="Type of content", name="Name to search")
    @app_commands.choices(content_type=SRD_TYPE_CHOICES)
    async def slash_srd(
        interaction: discord.Interaction,
        content_type: app_commands.Choice[str],
        name: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        query = name.strip()
        search, embed_fn = SRD_LOOKUPS[content_type.value]
        try:
            item = await search(query=query)
            if content_type.value == "class":
                embed, view = class_lookup_message(item)
                await send_interaction_message(interaction, embed=embed, view=view, ephemeral=True)
                return
            embed = embed_fn(item)
        except fivetools.Open5eError as exc:
            await send_interaction_message(interaction, content=str(exc), ephemeral=True)
            return
        await send_interaction_message(interaction, embed=embed, ephemeral=True)

    @slash_srd.autocomplete("name")
    async def srd_name_autocomplete(
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        kind = getattr(interaction.namespace, "content_type", None)
        if isinstance(kind, app_commands.Choice):
            kind = kind.value
        if not kind:
            return []
        return [
            app_commands.Choice(name=option[:100], value=option[:100])
            for option in fivetools.suggest_names(str(kind), current)
        ]
