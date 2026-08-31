import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.ext import commands

from bot.help_commands import (
    collect_all_help_embeds,
    send_all_help,
    setup_help,
)
from bot.help_text import (
    build_guide_help_embeds,
    is_help_all_topic,
    pack_embed_batches,
)
from bot.slash import setup_slash
from bot.trash_commands import setup_trash
from campaign.commands import setup_campaign
from campaign.time_commands import setup_time
from combat.commands import setup_combat
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


def _register_commands(bot: commands.Bot) -> None:
    for setup in (
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
    ):
        setup(bot)


def _bot() -> commands.Bot:
    bot = commands.Bot(command_prefix=";", intents=discord.Intents.none())
    _register_commands(bot)
    return bot


class TestHelpAllTopic(unittest.TestCase):
    def test_recognizes_all_aliases(self) -> None:
        self.assertTrue(is_help_all_topic("all"))
        self.assertTrue(is_help_all_topic("TOUT"))
        self.assertTrue(is_help_all_topic(" toutes "))
        self.assertFalse(is_help_all_topic("sheet"))
        self.assertFalse(is_help_all_topic(""))


class TestGuideDumpAndPacking(unittest.TestCase):
    def test_guide_dump_covers_every_catalog(self) -> None:
        player = build_guide_help_embeds(prefix=";", is_admin=False)
        admin = build_guide_help_embeds(prefix=";", is_admin=True)
        titles = " ".join(embed.title or "" for embed in player)
        self.assertIn("Arkann", titles)
        self.assertIn("Fiche", titles)
        self.assertIn("Combat", titles)
        self.assertIn("règles", titles)
        self.assertIn("Faim", titles)
        self.assertGreater(len(admin), len(player))
        self.assertFalse(
            any(
                "Les boutons changent de section" in (embed.footer.text or "")
                for embed in player
            )
        )

    def test_pack_respects_embed_and_char_limits(self) -> None:
        embeds = [
            discord.Embed(title=f"n{index}", description="x" * 40)
            for index in range(12)
        ]
        batches = pack_embed_batches(embeds, max_embeds=10, max_chars=200)
        self.assertTrue(all(1 <= len(batch) <= 10 for batch in batches))
        self.assertEqual(sum(len(batch) for batch in batches), 12)
        tight = pack_embed_batches(embeds[:3], max_embeds=10, max_chars=90)
        self.assertGreater(len(tight), 1)


class TestCollectAllHelp(unittest.TestCase):
    def test_includes_guides_and_command_pages(self) -> None:
        embeds = collect_all_help_embeds(_bot(), is_admin=False)
        titles = [embed.title or "" for embed in embeds]
        joined = "\n".join(titles)
        self.assertGreater(len(embeds), 30)
        self.assertTrue(any("Arkann" in title for title in titles))
        self.assertIn("❓ Commandes", titles)
        self.assertIn("❓ roll", titles)
        self.assertIn("❓ sheet gear bag", titles)
        self.assertIn("❓ combat board", titles)
        self.assertNotIn("❓ sheet", titles)
        self.assertNotIn("❓ help", joined)


@patch("bot.help_commands._HELP_ALL_PAUSE_SECONDS", 0)
class TestSendAllHelp(unittest.IsolatedAsyncioTestCase):
    def _ctx(self, *, in_guild: bool = True, forbidden=False) -> MagicMock:
        ctx = MagicMock()
        ctx.bot = _bot()
        ctx.guild = MagicMock() if in_guild else None
        if ctx.guild is not None:
            ctx.guild.get_member.return_value = None
        ctx.interaction = None
        ctx.send = AsyncMock()
        ctx.message.delete = AsyncMock()
        ctx.author = MagicMock()
        ctx.author.id = 1
        if forbidden:
            ctx.author.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), ""))
        else:
            ctx.author.send = AsyncMock()
        return ctx

    async def test_dms_every_batch_then_acks_in_channel(self) -> None:
        ctx = self._ctx()
        await send_all_help(ctx)
        self.assertGreaterEqual(ctx.author.send.await_count, 2)
        first = ctx.author.send.await_args_list[0]
        self.assertIn("Aide complète", first.kwargs.get("content") or "")
        self.assertIn(
            "Aide complète envoyée en MP", ctx.send.await_args.kwargs["content"]
        )

    async def test_explains_when_dms_are_closed(self) -> None:
        ctx = self._ctx(forbidden=True)
        await send_all_help(ctx)
        self.assertIn("messages privés", ctx.send.await_args.kwargs["content"])
        self.assertIn(";help all", ctx.send.await_args.kwargs["content"])
