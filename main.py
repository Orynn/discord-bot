import logging

import discord
from discord.ext import commands
from discord.voice_client import VoiceClient

# This bot does not use voice; skip optional PyNaCl/davey warnings at startup.
VoiceClient.warn_nacl = False
VoiceClient.warn_dave = False
from discord.flags import Intents

from bot.events import register_events
from bot.help_commands import maybe_send_command_help, setup_help
from bot.logging_config import setup_logging
from bot.slash import setup_slash
from bot.trash_commands import setup_trash
from bot.tree_utils import clamp_app_command_descriptions
from campaign.commands import setup_campaign
from campaign.time_commands import setup_time
from combat.commands import setup_combat
from combat.editor_server import start_editor_server, stop_editor_server
from config import CAMPAIGN_GUILD_ID, PREFIX, require_token
from data.db import init_db
from fun.commands import setup_fun
from image.commands import setup_image
from initiative.commands import setup_initiative
from npc.commands import setup_npc
from party.commands import setup_party
from pc.commands import setup_pc
from players.commands import setup_player
from roll.commands import setup_roll
from scene.commands import setup_desc
from scene.rp_commands import setup_rp
from sheets.commands import setup_sheet
from sheets.commands.hunger import setup_hunger
from srd.commands import setup_srd

init_db()
setup_logging()

logger = logging.getLogger(__name__)


class ArkannBot(commands.Bot):
    async def invoke(self, ctx: commands.Context) -> None:
        if await maybe_send_command_help(ctx):
            return
        await super().invoke(ctx)

    async def setup_hook(self) -> None:
        await start_editor_server()
        try:
            clamp_app_command_descriptions(self.tree)
            if CAMPAIGN_GUILD_ID is not None:
                guild = discord.Object(id=CAMPAIGN_GUILD_ID)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
            else:
                synced = await self.tree.sync()
            logger.info("Synced %s slash command(s).", len(synced))
        except Exception:
            logger.exception("Slash command sync failed")

    async def close(self) -> None:
        from campaign.wiki import close_session as close_wiki_session

        await stop_editor_server()
        await close_wiki_session()
        await super().close()


intents: Intents = discord.Intents.default()
intents.message_content = True

bot: ArkannBot = ArkannBot(
    command_prefix=commands.when_mentioned_or(PREFIX),
    intents=intents,
)

COMMAND_SETUPS = (
    setup_npc,
    setup_desc,
    setup_rp,
    setup_fun,
    setup_image,
    setup_pc,
    setup_roll,
    setup_sheet,
    setup_initiative,
    setup_party,
    setup_player,
    setup_srd,
    setup_campaign,
    setup_time,
    setup_hunger,
    setup_combat,
    setup_trash,
    setup_help,
    setup_slash,
)

for setup in COMMAND_SETUPS:
    setup(bot)

register_events(bot)

bot.run(token=require_token(), log_handler=None)
