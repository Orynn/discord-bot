import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from campaign.forums import (
    CampaignForumError,
    campaign_category_overwrites,
    ensure_campaign_category,
    ensure_default_campaign_forums,
    find_existing_thread,
    format_forum_channel_name,
    locate_campaign_thread,
    match_campaign_forum,
    parse_post_spec,
    starter_content,
)


class TestCampaignForums(unittest.TestCase):
    def test_formats_known_forum_names_with_emoji(self) -> None:
        self.assertEqual(format_forum_channel_name("lieux"), "📍 lieux")
        self.assertEqual(format_forum_channel_name("pnj"), "👤 pnj")
        self.assertEqual(format_forum_channel_name("quetes"), "🎯 quêtes")
        self.assertEqual(format_forum_channel_name("creatures"), "🐉 créatures")
        self.assertEqual(format_forum_channel_name("objets"), "⚔️ objets")
        self.assertEqual(format_forum_channel_name("spells"), "✨ sorts")
        self.assertEqual(format_forum_channel_name("divers"), "📦 divers")
        self.assertEqual(format_forum_channel_name("misc"), "📦 divers")
        self.assertEqual(format_forum_channel_name("flora"), "🌿 flore")
        self.assertEqual(format_forum_channel_name("vegetation"), "🌿 flore")
        self.assertEqual(format_forum_channel_name("race"), "🧝 race")
        self.assertEqual(format_forum_channel_name("ethnie"), "🧝 race")
        self.assertEqual(format_forum_channel_name("classe"), "🎓 classe")
        self.assertEqual(format_forum_channel_name("class"), "🎓 classe")
        self.assertEqual(format_forum_channel_name("📍 lieux"), "📍 lieux")

    def test_rejects_empty_forum_name(self) -> None:
        with self.assertRaises(CampaignForumError):
            format_forum_channel_name("   ")

    def test_parse_post_spec_splits_body(self) -> None:
        spec = parse_post_spec("lieux", "[Phandalin] Mines -- Au sud-est de Phandalin.")
        self.assertEqual(spec.section, "lieux")
        self.assertEqual(spec.title, "[Phandalin] Mines")
        self.assertEqual(spec.body, "Au sud-est de Phandalin.")

        piped = parse_post_spec("pnj", "[Phandalin] Toblen | Aubergiste")
        self.assertEqual(piped.title, "[Phandalin] Toblen")
        self.assertEqual(piped.body, "Aubergiste")

    def test_parse_post_spec_title_only(self) -> None:
        spec = parse_post_spec("lieux", "Phandalin")
        self.assertEqual(spec.title, "Phandalin")
        self.assertEqual(spec.body, "")

    def test_match_forum_ignores_emoji(self) -> None:
        forums = [
            SimpleNamespace(name="📍 lieux"),
            SimpleNamespace(name="👤 pnj"),
        ]
        matched = match_campaign_forum(forums, "lieux")  # type: ignore[arg-type]
        self.assertIsNotNone(matched)
        self.assertEqual(matched.name, "📍 lieux")

    def test_starter_content_placeholder(self) -> None:
        self.assertIn("Fiche à compléter", starter_content(title="Phandalin", body=""))
        self.assertEqual(starter_content(title="Phandalin", body="Petite ville."), "Petite ville.")

    def test_find_existing_thread_matches_name(self) -> None:
        thread = SimpleNamespace(name="Phandalin")
        forum = SimpleNamespace(name="📍 lieux", threads=[thread])
        found = find_existing_thread([forum], "phandalin")  # type: ignore[arg-type]
        self.assertIs(found, thread)
        self.assertIsNone(find_existing_thread([forum], "Neverwinter"))  # type: ignore[arg-type]


class TestLocateCampaignThread(unittest.IsolatedAsyncioTestCase):
    async def test_finds_archived_thread(self) -> None:
        archived = SimpleNamespace(name="Padhiver")

        async def archived_threads(*, limit: int = 100):
            yield archived

        forum = SimpleNamespace(name="📍 lieux", threads=[], archived_threads=archived_threads)
        found = await locate_campaign_thread([forum], "padhiver")  # type: ignore[arg-type]
        self.assertIs(found, archived)


def _role(
    *,
    id: int,
    name: str,
    administrator: bool = False,
    manage_guild: bool = False,
    default: bool = False,
    bot: bool = False,
) -> MagicMock:
    role = MagicMock()
    role.id = id
    role.name = name
    role.permissions.administrator = administrator
    role.permissions.manage_guild = manage_guild
    role.is_default.return_value = default
    role.is_bot_managed.return_value = bot
    return role


class TestCampaignCategoryOverwrites(unittest.TestCase):
    def test_hides_everyone_and_allows_bot_and_admins(self) -> None:
        everyone = _role(id=1, name="@everyone", default=True)
        admin = _role(id=2, name="Admin", administrator=True)
        manager = _role(id=3, name="Manager", manage_guild=True)
        player = _role(id=4, name="Player")
        bot_role = _role(id=5, name="Arkan", bot=True)
        bot = MagicMock()
        bot.id = 99
        owner = MagicMock()
        owner.id = 50
        guild = SimpleNamespace(
            default_role=everyone,
            roles=[everyone, admin, manager, player, bot_role],
            me=bot,
            owner=owner,
        )

        overwrites = campaign_category_overwrites(guild)  # type: ignore[arg-type]
        self.assertFalse(overwrites[everyone].view_channel)
        self.assertTrue(overwrites[bot].view_channel)
        self.assertTrue(overwrites[bot].manage_channels)
        self.assertTrue(overwrites[admin].view_channel)
        self.assertTrue(overwrites[manager].view_channel)
        self.assertTrue(overwrites[owner].view_channel)
        self.assertNotIn(player, overwrites)
        self.assertNotIn(bot_role, overwrites)

    def test_uses_owner_id_when_owner_member_is_missing(self) -> None:
        everyone = _role(id=1, name="@everyone", default=True)
        bot = MagicMock()
        bot.id = 99
        guild = SimpleNamespace(
            default_role=everyone,
            roles=[everyone],
            me=bot,
            owner=None,
            owner_id=50,
        )
        overwrites = campaign_category_overwrites(guild)  # type: ignore[arg-type]
        owner_ids = {getattr(target, "id", None) for target in overwrites}
        self.assertIn(50, owner_ids)

    def test_bot_only_privacy_omits_admin_roles(self) -> None:
        everyone = _role(id=1, name="@everyone", default=True)
        admin = _role(id=2, name="Admin", administrator=True)
        bot = MagicMock()
        bot.id = 99
        guild = SimpleNamespace(
            default_role=everyone,
            roles=[everyone, admin],
            me=bot,
            owner=None,
            owner_id=None,
        )
        overwrites = campaign_category_overwrites(guild, include_admin_roles=False)  # type: ignore[arg-type]
        self.assertNotIn(admin, overwrites)
        self.assertIn(everyone, overwrites)
        self.assertIn(bot, overwrites)


class TestEnsureCampaignCategory(unittest.IsolatedAsyncioTestCase):
    async def test_recreates_missing_category(self) -> None:
        created = SimpleNamespace(id=99, name="CAMPAIGN")
        everyone = _role(id=1, name="@everyone", default=True)
        guild = MagicMock()
        guild.id = 11
        guild.name = "Test Guild"
        guild.default_role = everyone
        guild.roles = [everyone]
        guild.owner = None
        guild.owner_id = None
        me = MagicMock()
        me.id = 7
        me.guild_permissions.manage_channels = True
        guild.me = me
        guild.create_category = AsyncMock(return_value=created)

        with (
            patch("campaign.forums.find_campaign_category", return_value=None),
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
            patch("campaign.forums.app_config.set_campaign_category_id") as persist,
        ):
            category = await ensure_campaign_category(guild)

        self.assertIs(category, created)
        guild.create_category.assert_awaited_once()
        kwargs = guild.create_category.await_args.kwargs
        self.assertIn("overwrites", kwargs)
        self.assertFalse(kwargs["overwrites"][everyone].view_channel)
        persist.assert_called_once_with(99, guild_id=11)

    async def test_retries_with_bot_only_overwrites_on_forbidden(self) -> None:
        created = SimpleNamespace(id=99, name="CAMPAIGN")
        everyone = _role(id=1, name="@everyone", default=True)
        admin = _role(id=2, name="Admin", administrator=True)
        response = MagicMock()
        response.status = 403
        response.reason = "Forbidden"
        guild = MagicMock()
        guild.id = 11
        guild.name = "Test Guild"
        guild.default_role = everyone
        guild.roles = [everyone, admin]
        guild.owner = None
        guild.owner_id = 50
        me = MagicMock()
        me.id = 7
        me.guild_permissions.manage_channels = True
        guild.me = me
        guild.create_category = AsyncMock(
            side_effect=[discord.Forbidden(response, "Missing Permissions"), created]
        )

        with (
            patch("campaign.forums.find_campaign_category", return_value=None),
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
            patch("campaign.forums.app_config.set_campaign_category_id") as persist,
        ):
            category = await ensure_campaign_category(guild)

        self.assertIs(category, created)
        self.assertEqual(guild.create_category.await_count, 2)
        second_overwrites = guild.create_category.await_args_list[1].kwargs["overwrites"]
        self.assertNotIn(admin, second_overwrites)
        persist.assert_called_once_with(99, guild_id=11)

    async def test_reuses_existing_category(self) -> None:
        existing = SimpleNamespace(id=7, name="CAMPAIGN")
        guild = MagicMock()
        guild.id = 11
        guild.create_category = AsyncMock()

        with (
            patch("campaign.forums.find_campaign_category", return_value=existing),
            patch("campaign.forums.app_config.CAMPAIGN_CATEGORY_ID", 7),
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
            patch("campaign.forums.app_config.set_campaign_category_id") as persist,
        ):
            category = await ensure_campaign_category(guild)

        self.assertIs(category, existing)
        guild.create_category.assert_not_called()
        persist.assert_not_called()

    async def test_does_not_persist_other_guild_campaign_category(self) -> None:
        existing = SimpleNamespace(id=88, name="CAMPAIGN")
        guild = MagicMock()
        guild.id = 22
        guild.create_category = AsyncMock()

        with (
            patch("campaign.forums.find_campaign_category", return_value=existing),
            patch("campaign.forums.app_config.CAMPAIGN_CATEGORY_ID", 7),
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
            patch("campaign.forums.app_config.set_campaign_category_id") as persist,
        ):
            category = await ensure_campaign_category(guild)

        self.assertIs(category, existing)
        guild.create_category.assert_not_called()
        persist.assert_not_called()

    async def test_skips_creating_forums_on_other_guild(self) -> None:
        existing = SimpleNamespace(id=88, name="CAMPAIGN")
        guild = MagicMock()
        guild.id = 22
        guild.name = "Other"
        guild.create_forum = AsyncMock()

        with (
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
            patch("campaign.forums.find_campaign_category", return_value=existing),
            patch("campaign.forums.list_campaign_forums", return_value=["existing"]),
            patch("campaign.forums.ensure_campaign_category") as ensure_category,
        ):
            forums = await ensure_default_campaign_forums(guild)

        self.assertEqual(forums, ["existing"])
        ensure_category.assert_not_called()
        guild.create_forum.assert_not_called()

    async def test_skips_other_guild_without_permission(self) -> None:
        guild = MagicMock()
        guild.id = 22
        guild.name = "Le Moulin"
        guild.me = SimpleNamespace(guild_permissions=SimpleNamespace(manage_channels=False))
        guild.create_category = AsyncMock()

        with (
            patch("campaign.forums.find_campaign_category", return_value=None),
            patch("campaign.forums.app_config.CAMPAIGN_GUILD_ID", 11),
        ):
            forums = await ensure_default_campaign_forums(guild)

        self.assertEqual(forums, [])
        guild.create_category.assert_not_called()
