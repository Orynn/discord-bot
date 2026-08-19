import discord

from combat.view import register_combat_views
from sheets.spell_view import SpellSelectView
from srd.definition_view import DefinitionSelectView


def register_persistent_views(bot: discord.Client) -> None:
    bot.add_view(SpellSelectView())
    bot.add_view(DefinitionSelectView())
    register_combat_views(bot)
