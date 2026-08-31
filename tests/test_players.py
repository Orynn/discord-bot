import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import data.db as db_module
from players.setup import build_welcome_embed, ensure_player_sheet
from players.storage import (
    delete_player_section,
    get_player_section,
    list_player_sections,
    save_player_section,
)
from sheets.storage import get_character_name, get_sheet


class TestPlayerStorage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_list_and_delete(self) -> None:
        save_player_section(
            guild_id=1,
            user_id=42,
            data={"name": "LEO", "category_id": 100},
        )
        save_player_section(
            guild_id=1,
            user_id=99,
            data={"name": "BOB", "category_id": 101},
        )

        entries = list_player_sections(guild_id=1)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0][1]["name"], "BOB")

        removed = delete_player_section(guild_id=1, user_id=42)
        assert removed is not None
        self.assertEqual(removed["name"], "LEO")
        self.assertIsNone(get_player_section(guild_id=1, user_id=42))
        self.assertEqual(len(list_player_sections(guild_id=1)), 1)

    def test_finds_player_from_section_channel(self) -> None:
        from players.storage import find_player_id_for_channel

        save_player_section(
            guild_id=1,
            user_id=42,
            data={
                "name": "LEO",
                "category_id": 100,
                "ooc_channel_id": 201,
                "roleplay_channel_id": 202,
            },
        )
        self.assertEqual(
            find_player_id_for_channel(guild_id=1, channel_id=201, category_id=100), 42
        )
        self.assertEqual(
            find_player_id_for_channel(guild_id=1, channel_id=202, category_id=None), 42
        )
        self.assertEqual(
            find_player_id_for_channel(guild_id=1, channel_id=999, category_id=100), 42
        )
        self.assertIsNone(
            find_player_id_for_channel(guild_id=1, channel_id=999, category_id=888)
        )


class TestDiscoverPlayerSection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_discovers_blabla_from_overwrites(self) -> None:
        from players.discover import discover_player_id
        from players.setup import ensure_player_sheet

        ensure_player_sheet(user_id=42, guild_id=1, name="Graosh")

        player = MagicMock(spec=__import__("discord").Member)
        player.id = 42
        player.bot = False
        player.display_name = "Graosh"
        player.name = "graosh"
        player.guild_permissions.administrator = False
        player.guild_permissions.manage_guild = False

        overwrite = MagicMock()
        overwrite.view_channel = True

        category = MagicMock()
        category.id = 100
        category.name = "🐉-----------GRAOSH-----------🐉"
        category.channels = []
        category.overwrites = {player: overwrite}

        channel = MagicMock()
        channel.id = 201
        channel.name = "📢blabla"
        channel.category = category
        channel.category_id = 100
        channel.overwrites = {}

        category.channels = [channel]

        guild = MagicMock()
        guild.id = 1
        guild.owner_id = 99
        guild.members = [player]
        guild.me = None

        self.assertEqual(discover_player_id(guild=guild, channel=channel), 42)

    def test_trash_channel_is_sandbox_not_a_player_section(self) -> None:
        from players.discover import (
            discover_player_id,
            is_sandbox_channel,
            sandbox_scope_id,
        )

        trash = MagicMock()
        trash.id = 404
        trash.name = "🚯trash"
        trash.category_id = 88
        trash.category = MagicMock(id=88, name="staff", channels=[])
        self.assertTrue(is_sandbox_channel(trash))
        self.assertEqual(sandbox_scope_id(trash), 404)

        guild = MagicMock()
        guild.id = 1
        guild.members = []
        self.assertIsNone(discover_player_id(guild=guild, channel=trash))

    def test_discovers_uncached_overwrite_when_category_is_nickname(self) -> None:
        import discord
        from players.discover import discover_player_id
        from players.setup import ensure_player_sheet

        ensure_player_sheet(user_id=42, guild_id=1, name="Graosh")

        player = discord.Object(id=42, type=discord.abc.User)
        extra = discord.Object(id=99, type=discord.abc.User)
        player_overwrite = discord.PermissionOverwrite(view_channel=True)
        extra_overwrite = discord.PermissionOverwrite(view_channel=True)

        category = MagicMock()
        category.id = 100
        category.name = "🐉-----------FOX------------🐉"
        category.channels = []
        category.overwrites = {player: player_overwrite, extra: extra_overwrite}
        category._overwrites = "not-a-list"

        channel = MagicMock()
        channel.id = 201
        channel.name = "📢blabla"
        channel.category = category
        channel.category_id = 100
        channel.overwrites = {}
        channel._overwrites = "not-a-list"
        category.channels = [channel]

        guild = MagicMock()
        guild.id = 1
        guild.owner_id = 1
        guild.members = []
        guild.me = discord.Object(id=555)
        guild.get_member.return_value = None

        self.assertEqual(discover_player_id(guild=guild, channel=channel), 42)

    def test_discovers_from_raw_member_overwrites(self) -> None:
        from players.discover import discover_player_id
        from players.setup import ensure_player_sheet

        ensure_player_sheet(user_id=42, guild_id=1, name="Graosh")

        raw_player = MagicMock()
        raw_player.id = 42
        raw_player.allow = 1024
        raw_player.deny = 0
        raw_player.is_member.return_value = True
        raw_player.type = 1

        raw_role = MagicMock()
        raw_role.id = 1
        raw_role.allow = 0
        raw_role.deny = 1024
        raw_role.is_member.return_value = False
        raw_role.type = 0

        category = MagicMock()
        category.id = 100
        category.name = "🐉-----------FOX------------🐉"
        category.channels = []
        category.overwrites = {}
        category._overwrites = [raw_role, raw_player]

        channel = MagicMock()
        channel.id = 201
        channel.name = "📢blabla"
        channel.category = category
        channel.category_id = 100
        channel.overwrites = {}
        channel._overwrites = []
        category.channels = [channel]

        guild = MagicMock()
        guild.id = 1
        guild.owner_id = 1
        guild.members = []
        guild.me = None
        guild.get_member.return_value = None

        self.assertEqual(discover_player_id(guild=guild, channel=channel), 42)

    def test_discovers_from_category_name_and_sheet(self) -> None:
        from players.discover import discover_player_id
        from players.setup import ensure_player_sheet

        ensure_player_sheet(user_id=7, guild_id=1, name="Ilidor")

        category = MagicMock()
        category.id = 50
        category.name = "🐉-----------ILIDOR-----------🐉"
        category.channels = []
        category.overwrites = {}

        channel = MagicMock()
        channel.id = 80
        channel.name = "blabla"
        channel.category = category
        channel.category_id = 50
        channel.overwrites = {}
        category.channels = [channel]

        guild = MagicMock()
        guild.id = 1
        guild.owner_id = 1
        guild.members = []
        guild.me = None

        self.assertEqual(discover_player_id(guild=guild, channel=channel), 7)

    def test_sync_persists_mapping_and_drops_stale_sections(self) -> None:
        import discord
        from players.discover import sync_guild_player_sections
        from players.setup import ensure_player_sheet
        from players.storage import (
            find_player_id_for_channel,
            get_player_section,
            save_player_section,
        )

        ensure_player_sheet(user_id=42, guild_id=1, name="Graosh")
        save_player_section(
            guild_id=1,
            user_id=99,
            data={"name": "GONE", "category_id": 999, "ooc_channel_id": 1},
        )

        player = discord.Object(id=42, type=discord.abc.User)
        overwrite = discord.PermissionOverwrite(view_channel=True)

        category = MagicMock()
        category.id = 100
        category.name = "🐉-----------FOX------------🐉"
        category.overwrites = {player: overwrite}
        category._overwrites = "not-a-list"

        channel = MagicMock()
        channel.id = 201
        channel.name = "📢blabla"
        channel.category = category
        channel.overwrites = {}
        channel._overwrites = "not-a-list"
        category.channels = [channel]

        guild = MagicMock()
        guild.id = 1
        guild.owner_id = 1
        guild.members = []
        guild.me = discord.Object(id=555)
        guild.categories = [category]
        guild.get_member.return_value = None
        guild.get_channel.side_effect = lambda channel_id: (
            category if channel_id == 100 else None
        )

        self.assertEqual(sync_guild_player_sections(guild), 1)
        self.assertEqual(
            find_player_id_for_channel(guild_id=1, channel_id=201, category_id=100), 42
        )
        self.assertIsNone(get_player_section(guild_id=1, user_id=99))
        self.assertIsNotNone(get_player_section(guild_id=1, user_id=42))


class TestEnsurePlayerSheet(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_db = db_module.DB_FILE
        db_module.DB_FILE = Path(self._tmpdir.name) / "test.db"
        db_module.init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._original_db
        self._tmpdir.cleanup()

    def test_creates_sheet_and_pcname(self) -> None:
        sheet, created = ensure_player_sheet(user_id=7, guild_id=1, name="Magnus")
        self.assertTrue(created)
        self.assertEqual(sheet.name, "Magnus")
        self.assertEqual(get_character_name(user_id=7, guild_id=1), "Magnus")
        self.assertIsNotNone(get_sheet(user_id=7, guild_id=1))

    def test_updates_existing_sheet_name(self) -> None:
        ensure_player_sheet(user_id=7, guild_id=1, name="Old Name")
        _, created = ensure_player_sheet(user_id=7, guild_id=1, name="New Name")
        self.assertFalse(created)
        self.assertEqual(get_sheet(user_id=7, guild_id=1).name, "New Name")
        self.assertEqual(get_character_name(user_id=7, guild_id=1), "New Name")


class TestWelcomeEmbed(unittest.TestCase):
    def test_includes_character_name(self) -> None:
        member = MagicMock()
        member.mention = "@Player"
        embed = build_welcome_embed(character_name="Leo", member=member)
        self.assertIn("Leo", embed.title)
        text = (embed.description or "") + "".join(
            field.value for field in embed.fields
        )
        self.assertIn(";sheet show", text)


if __name__ == "__main__":
    unittest.main()
