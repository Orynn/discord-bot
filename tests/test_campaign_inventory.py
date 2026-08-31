import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import discord

from campaign.inventory import (
    collect_guild_channels,
    format_channel_list,
    write_channel_export,
)


def _category(id: int, name: str, position: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        name=name,
        position=position,
        type=discord.ChannelType.category,
    )


def _channel(
    id: int,
    name: str,
    *,
    kind: discord.ChannelType,
    position: int,
    category: SimpleNamespace | None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        name=name,
        type=kind,
        position=position,
        category=category,
    )


def _guild() -> SimpleNamespace:
    campaign = _category(1, "CAMPAIGN", 0)
    general = _category(2, "GENERAL", 1)
    forums = _channel(
        10,
        "📍 lieux",
        kind=discord.ChannelType.forum,
        position=0,
        category=campaign,
    )
    pnj = _channel(
        11,
        "👤 pnj",
        kind=discord.ChannelType.forum,
        position=1,
        category=campaign,
    )
    chat = _channel(
        20,
        "general",
        kind=discord.ChannelType.text,
        position=0,
        category=general,
    )
    uncategorized = _channel(
        30,
        "mod-log",
        kind=discord.ChannelType.text,
        position=0,
        category=None,
    )
    return SimpleNamespace(
        id=42,
        name="Potato Head",
        channels=[forums, pnj, chat, uncategorized, campaign, general],
        categories=[campaign, general],
    )


class TestCampaignInventory(unittest.TestCase):
    def test_collects_channels_grouped_by_category(self) -> None:
        rows = collect_guild_channels(_guild())  # type: ignore[arg-type]
        names = [row.name for row in rows]
        self.assertEqual(names, ["📍 lieux", "👤 pnj", "general", "mod-log"])
        self.assertEqual(rows[0].category, "CAMPAIGN")
        self.assertEqual(rows[0].kind, "forum")
        self.assertEqual(rows[2].kind, "text")
        self.assertEqual(rows[3].category, "")

    def test_format_lists_forums_and_categories(self) -> None:
        text = format_channel_list(_guild())  # type: ignore[arg-type]
        self.assertIn("# Potato Head", text)
        self.assertIn("## Forums (2)", text)
        self.assertIn("- 📍 lieux  [CAMPAIGN]", text)
        self.assertIn("## CAMPAIGN", text)
        self.assertIn("forum         📍 lieux", text)
        self.assertIn("## GENERAL", text)
        self.assertIn("## (no category)", text)

    def test_write_channel_export_creates_txt_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            export_dir = Path(tmp)
            with patch("campaign.inventory.EXPORT_DIR", export_dir):
                path = write_channel_export(_guild())  # type: ignore[arg-type]
            self.assertEqual(path.name, "42-channels.txt")
            self.assertTrue(path.exists())
            json_path = path.with_suffix(".json")
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["channel"], "📍 lieux")
            self.assertEqual(payload[0]["category"], "CAMPAIGN")
            self.assertEqual(payload[0]["type"], "forum")
