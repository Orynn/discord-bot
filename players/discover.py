import logging
import re
from typing import Any

import discord

from bot.checks import is_staff_member, is_staff_user_id
from config import CAMPAIGN_CATEGORY_ID, PLAYER_CHANNEL_OOC, PLAYER_CHANNEL_RP
from players.storage import (
    delete_player_section,
    find_player_id_for_channel,
    get_player_section,
    list_player_sections,
    save_player_section,
)
from sheets.storage import find_user_id_by_character_name, get_sheet

logger = logging.getLogger(__name__)

_PLAIN = re.compile(r"[^a-z0-9]+")
SANDBOX_CHANNEL_KEY = "trash"


def _plain_name(name: str | None) -> str:
    if not isinstance(name, str):
        return ""
    return _PLAIN.sub("", name.casefold())


def _unwrap_channel(channel: Any) -> Any:
    if (
        isinstance(channel, discord.Thread)
        and getattr(channel, "parent", None) is not None
    ):
        return channel.parent
    return channel


def is_sandbox_channel(channel: Any) -> bool:
    """True for #🚯trash (and any name that strips to 'trash')."""
    channel = _unwrap_channel(channel)
    if channel is None:
        return False
    return _plain_name(getattr(channel, "name", None)) == SANDBOX_CHANNEL_KEY


def sandbox_scope_id(channel: Any) -> int | None:
    channel = _unwrap_channel(channel)
    if channel is None or not is_sandbox_channel(channel):
        return None
    channel_id = getattr(channel, "id", None)
    if channel_id is None:
        return None
    return int(channel_id)


def sandbox_player_id(channel: Any) -> int | None:
    """Reserved negative id so trash never writes a real Discord user's sheet."""
    scope = sandbox_scope_id(channel)
    if scope is None:
        return None
    return -abs(scope)


def is_sandbox_owner_id(user_id: int | None) -> bool:
    return user_id is not None and int(user_id) < 0


def _is_player_channel_name(name: str | None) -> bool:
    plain = _plain_name(name)
    if not plain:
        return False
    ooc = _plain_name(PLAYER_CHANNEL_OOC)
    rp = _plain_name(PLAYER_CHANNEL_RP)
    return (
        plain == ooc
        or plain == rp
        or ooc in plain
        or rp in plain
        or "blabla" in plain
        or "roleplay" in plain
    )


def _label_from_category_name(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = re.sub(r"^[^A-Za-z0-9]+", "", name)
    cleaned = re.sub(r"[^A-Za-z0-9]+$", "", cleaned)
    cleaned = cleaned.strip("- ").strip()
    return cleaned or None


def _ignored_category(category: Any) -> bool:
    if category is None:
        return False
    category_id = getattr(category, "id", None)
    if CAMPAIGN_CATEGORY_ID is not None and category_id == CAMPAIGN_CATEGORY_ID:
        return True
    label = _plain_name(getattr(category, "name", None))
    return label in {"campaign", "staff"}


def _looks_like_player_section(channel: Any, category: Any) -> bool:
    if _ignored_category(category):
        return False
    if _is_player_channel_name(getattr(channel, "name", None)):
        return True
    if category is None:
        return False
    if _label_from_category_name(getattr(category, "name", None)):
        children = getattr(category, "channels", None) or []
        if any(
            _is_player_channel_name(getattr(child, "name", None)) for child in children
        ):
            return True
        if _is_player_channel_name(getattr(category, "name", None)):
            return True
    return False


def _is_role_target(dest: Any) -> bool:
    if isinstance(dest, discord.Role):
        return True
    dest_type = getattr(dest, "type", None)
    return dest_type is discord.Role or dest_type == 0


def _overwrite_allows_view(overwrite: Any) -> bool:
    if overwrite is None:
        return False
    if getattr(overwrite, "view_channel", None) is True:
        return True
    if getattr(overwrite, "read_messages", None) is True:
        return True
    pair = getattr(overwrite, "pair", None)
    if callable(pair):
        try:
            allow, deny = pair()
        except (TypeError, ValueError):
            return False
        if getattr(deny, "view_channel", False):
            return False
        return bool(
            getattr(allow, "view_channel", False)
            or getattr(allow, "read_messages", False)
        )
    return False


def _skip_user_id(guild: discord.Guild, user_id: int, dest: Any = None) -> bool:
    bot_id = guild.me.id if getattr(guild, "me", None) is not None else None
    if bot_id is not None and user_id == bot_id:
        return True
    if user_id == guild.id:
        return True
    if is_staff_user_id(user_id):
        return True
    if dest is not None and getattr(dest, "bot", False):
        return True
    member = dest if isinstance(dest, discord.Member) else guild.get_member(user_id)
    if member is not None and (
        getattr(member, "bot", False) or is_staff_member(guild, member)
    ):
        return True
    return False


def _member_ids_from_raw(guild: discord.Guild, target: Any) -> list[int] | None:
    raw = getattr(target, "_overwrites", None)
    if not isinstance(raw, (list, tuple)):
        return None
    ids: list[int] = []
    for ow in raw:
        is_member = getattr(ow, "is_member", None)
        if callable(is_member):
            if not is_member():
                continue
        elif getattr(ow, "type", None) != 1:
            continue
        try:
            allow = discord.Permissions(int(getattr(ow, "allow", 0)))
            deny = discord.Permissions(int(getattr(ow, "deny", 0)))
        except (TypeError, ValueError):
            continue
        if deny.view_channel or not (allow.view_channel or allow.read_messages):
            continue
        user_id = int(ow.id)
        if _skip_user_id(guild, user_id):
            continue
        if user_id not in ids:
            ids.append(user_id)
    return ids


def _member_ids_with_view(guild: discord.Guild, target: Any) -> list[int]:
    from_raw = _member_ids_from_raw(guild, target)
    if from_raw is not None:
        return from_raw
    overwrites = getattr(target, "overwrites", None) or {}
    if not isinstance(overwrites, dict):
        return []
    ids: list[int] = []
    for dest, overwrite in overwrites.items():
        if _is_role_target(dest):
            continue
        user_id = getattr(dest, "id", None)
        if user_id is None:
            continue
        if not _overwrite_allows_view(overwrite):
            continue
        user_id = int(user_id)
        if _skip_user_id(guild, user_id, dest):
            continue
        if user_id not in ids:
            ids.append(user_id)
    return ids


def _player_from_overwrites(
    guild: discord.Guild, channel: Any, category: Any
) -> int | None:
    candidates: list[int] = []
    for target in (channel, category):
        if target is None:
            continue
        for user_id in _member_ids_with_view(guild, target):
            if user_id not in candidates:
                candidates.append(user_id)
    if not candidates:
        return None
    sheeted = [
        user_id
        for user_id in candidates
        if get_sheet(user_id=user_id, guild_id=guild.id)
    ]
    if len(sheeted) == 1:
        return sheeted[0]
    if len(candidates) == 1:
        return candidates[0]

    labeled = _label_from_category_name(getattr(category, "name", None))
    if labeled:
        named = find_user_id_by_character_name(guild_id=guild.id, name=labeled)
        if named in candidates:
            return named
    if len(sheeted) == 1:
        return sheeted[0]
    if sheeted:
        return sheeted[0]
    return None


def _remember_section(
    *, guild: discord.Guild, user_id: int, channel: Any, category: Any
) -> None:
    if category is None and channel is None:
        return
    existing = get_player_section(guild_id=guild.id, user_id=user_id) or {}
    ooc_id = existing.get("ooc_channel_id")
    rp_id = existing.get("roleplay_channel_id")
    channels = list(getattr(category, "channels", None) or [])
    if channel is not None and channel not in channels:
        channels.append(channel)
    for child in channels:
        name = getattr(child, "name", "")
        plain = _plain_name(name)
        if plain == _plain_name(PLAYER_CHANNEL_OOC) or "blabla" in plain:
            ooc_id = getattr(child, "id", None)
        elif plain == _plain_name(PLAYER_CHANNEL_RP) or "roleplay" in plain:
            rp_id = getattr(child, "id", None)
    label = _label_from_category_name(getattr(category, "name", None)) or str(user_id)
    category_id = getattr(category, "id", None)
    save_player_section(
        guild_id=guild.id,
        user_id=user_id,
        data={
            "name": existing.get("name") or label.upper(),
            "category_id": category_id,
            "ooc_channel_id": ooc_id or getattr(channel, "id", None),
            "roleplay_channel_id": rp_id,
            "discovered": True,
        },
    )
    if category_id is None:
        return
    for other_id, record in list_player_sections(guild_id=guild.id):
        if other_id == user_id:
            continue
        try:
            other_category = int(record.get("category_id"))
        except (TypeError, ValueError):
            continue
        if other_category == int(category_id):
            delete_player_section(guild_id=guild.id, user_id=other_id)


def _resolve_category(guild: discord.Guild, channel: Any) -> Any:
    category = getattr(channel, "category", None)
    if category is not None:
        return category
    category_id = getattr(channel, "category_id", None)
    if category_id is None:
        return None
    getter = getattr(guild, "get_channel", None)
    if callable(getter):
        found = getter(category_id)
        if found is not None:
            return found
    return None


def discover_player_id(*, guild: discord.Guild, channel: Any) -> int | None:
    channel = _unwrap_channel(channel)
    if channel is None or is_sandbox_channel(channel):
        return None
    category = _resolve_category(guild, channel)
    category_id = getattr(category, "id", None)
    if category_id is None:
        category_id = getattr(channel, "category_id", None)

    stored = find_player_id_for_channel(
        guild_id=guild.id,
        channel_id=getattr(channel, "id", None),
        category_id=category_id,
    )
    if stored is not None:
        return stored

    if not _looks_like_player_section(channel, category):
        return None

    found = _player_from_overwrites(guild, channel, category)
    if found is None:
        label = _label_from_category_name(getattr(category, "name", None))
        if label:
            found = find_user_id_by_character_name(guild_id=guild.id, name=label)
            if found is None:
                needle = label.casefold()
                for member in guild.members:
                    names = [
                        getattr(member, "display_name", None),
                        getattr(member, "name", None),
                        getattr(member, "global_name", None),
                    ]
                    if any(str(name).casefold() == needle for name in names if name):
                        if not is_staff_member(guild, member):
                            found = member.id
                            break
    if found is None:
        logger.info(
            "No player section for #%s (%s) in %s",
            getattr(channel, "id", None),
            getattr(channel, "name", None),
            getattr(category, "name", None),
        )
        return None
    try:
        _remember_section(
            guild=guild, user_id=found, channel=channel, category=category
        )
    except Exception:
        logger.exception("Could not remember player section for %s", found)
    return found


def _prune_missing_player_sections(guild: discord.Guild) -> None:
    getter = getattr(guild, "get_channel", None)
    if not callable(getter):
        return
    for user_id, record in list_player_sections(guild_id=guild.id):
        try:
            category_id = int(record.get("category_id"))
        except (TypeError, ValueError):
            continue
        if getter(category_id) is None:
            delete_player_section(guild_id=guild.id, user_id=user_id)


def sync_guild_player_sections(guild: discord.Guild) -> int:
    saved = 0
    for category in getattr(guild, "categories", None) or []:
        if _ignored_category(category):
            continue
        children = list(getattr(category, "channels", None) or [])
        if not any(
            _is_player_channel_name(getattr(child, "name", None)) for child in children
        ):
            continue
        channel = next(
            (
                child
                for child in children
                if _is_player_channel_name(getattr(child, "name", None))
            ),
            None,
        )
        found = _player_from_overwrites(guild, channel, category)
        if found is None:
            label = _label_from_category_name(getattr(category, "name", None))
            if label:
                found = find_user_id_by_character_name(guild_id=guild.id, name=label)
        if found is None:
            continue
        _remember_section(
            guild=guild, user_id=found, channel=channel, category=category
        )
        saved += 1
    _prune_missing_player_sections(guild)
    return saved


def refresh_guild_player_sections(guild: discord.Guild | None) -> int:
    if guild is None:
        return 0
    return sync_guild_player_sections(guild)
