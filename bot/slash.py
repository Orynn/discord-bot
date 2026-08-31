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
from srd.fivetools.lookup import lookup_candidates, parse_search_query
from srd.search_view import SrdMatchView, build_match_prompt

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
    @bot.tree.command(
        name="srd", description="Look up rules content from your 5etools export"
    )
    @app_commands.describe(
        content_type="Type of content",
        name="Name to search. Prefix ~ to list close matches",
    )
    @app_commands.choices(content_type=SRD_TYPE_CHOICES)
    async def slash_srd(
        interaction: discord.Interaction,
        content_type: app_commands.Choice[str],
        name: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        text, force_fuzzy = parse_search_query(name)
        kind = content_type.value
        search, embed_fn = SRD_LOOKUPS[kind]
        try:
            if not text:
                raise fivetools.FiveToolsNotFoundError("Missing search text.")
            candidates = lookup_candidates(kind, text, force_list=force_fuzzy)
            if candidates is not None:
                if not candidates:
                    raise fivetools.FiveToolsNotFoundError(
                        f"No {kind} found matching '{text}'."
                    )
                if len(candidates) > 1:
                    await send_interaction_message(
                        interaction,
                        embed=build_match_prompt(query=text, matches=candidates),
                        view=SrdMatchView(kind=kind, matches=candidates),
                        ephemeral=True,
                    )
                    return
                item = await search(query=str(candidates[0].get("name") or text))
            else:
                item = await search(query=text)
            if kind == "class":
                embed, view = class_lookup_message(item)
                await send_interaction_message(
                    interaction, embed=embed, view=view, ephemeral=True
                )
                return
            embed = embed_fn(item)
        except fivetools.Open5eError as exc:
            await send_interaction_message(
                interaction, content=str(exc), ephemeral=True
            )
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
        text, _force = parse_search_query(current)
        return [
            app_commands.Choice(name=option[:100], value=option[:100])
            for option in fivetools.suggest_names(str(kind), text)
        ]
