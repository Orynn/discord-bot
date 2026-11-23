"""Sync slash commands only when they changed.

Discord rate-limits bulk command updates: syncing on every restart made a
quick restart wait ~40 s. A hash of the command payload is kept in the DB.
"""

import hashlib
import json
from typing import Any

import discord
from discord import app_commands

from data.db import get_json, set_json


def commands_payload(
    tree: app_commands.CommandTree, guild: discord.abc.Snowflake | None
) -> list[dict[str, Any]]:
    return sorted(
        (command.to_dict(tree) for command in tree.get_commands(guild=guild)),
        key=lambda item: (str(item.get("type")), str(item.get("name"))),
    )


def payload_hash(payload: list[dict[str, Any]]) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _key(guild: discord.abc.Snowflake | None) -> str:
    return f"slash_sync_hash:{guild.id if guild is not None else 'global'}"


def needs_sync(
    tree: app_commands.CommandTree, guild: discord.abc.Snowflake | None
) -> bool:
    return get_json(_key(guild)) != payload_hash(commands_payload(tree, guild))


def remember_sync(
    tree: app_commands.CommandTree, guild: discord.abc.Snowflake | None
) -> None:
    set_json(_key(guild), payload_hash(commands_payload(tree, guild)))
