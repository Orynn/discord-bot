from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord

import config as app_config
from campaign.lore import _section_label, find_campaign_category, markdown_channel_link

logger = logging.getLogger(__name__)

DEFAULT_CAMPAIGN_FORUMS: tuple[str, ...] = (
    "lieux",
    "pnj",
    "race",
    "classe",
    "créatures",
    "flore",
    "pantheon",
    "organisations",
    "quêtes",
    "objets",
    "sorts",
    "divers",
)

DEFAULT_FORUM_EMOJIS: dict[str, str] = {
    "lieux": "📍",
    "pnj": "👤",
    "race": "🧝",
    "classe": "🎓",
    "créatures": "🐉",
    "flore": "🌿",
    "pantheon": "📜",
    "organisations": "🏘️",
    "quêtes": "🎯",
    "objets": "⚔️",
    "sorts": "✨",
    "divers": "📦",
}

_SECTION_ALIASES: dict[str, str] = {
    "quete": "quêtes",
    "quetes": "quêtes",
    "quête": "quêtes",
    "creature": "créatures",
    "creatures": "créatures",
    "flora": "flore",
    "vegetation": "flore",
    "végétation": "flore",
    "plante": "flore",
    "plantes": "flore",
    "plant": "flore",
    "plants": "flore",
    "races": "race",
    "ethnie": "race",
    "ethnies": "race",
    "species": "race",
    "class": "classe",
    "classes": "classe",
    "item": "objets",
    "items": "objets",
    "spell": "sorts",
    "spells": "sorts",
    "misc": "divers",
    "miscellaneous": "divers",
    "autre": "divers",
    "autres": "divers",
}

_BODY_SEPARATORS = (" -- ", " | ", "\n")


class CampaignForumError(Exception):
    pass


@dataclass(frozen=True)
class CampaignPostSpec:
    section: str
    title: str
    body: str


def normalize_section_key(name: str) -> str:
    key = _section_label(name).casefold().strip()
    return _SECTION_ALIASES.get(key, key)


def format_forum_channel_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise CampaignForumError("Forum name cannot be empty.")

    if _section_label(cleaned) != cleaned:
        return cleaned[:100]

    key = normalize_section_key(cleaned)
    emoji = DEFAULT_FORUM_EMOJIS.get(key)
    if emoji:
        return f"{emoji} {key}"[:100]
    return cleaned[:100]


def parse_post_spec(section: str, details: str) -> CampaignPostSpec:
    raw_section = section.strip()
    text = details.strip()
    if not raw_section:
        raise CampaignForumError("Missing forum name. Example: `lieux`, `pnj`, `quêtes`.")
    if not text:
        raise CampaignForumError("Missing post title.")

    body = ""
    for separator in _BODY_SEPARATORS:
        if separator in text:
            text, body = text.split(separator, 1)
            body = body.strip()
            break

    title = " ".join(text.split())
    if not title:
        raise CampaignForumError("Missing post title.")
    return CampaignPostSpec(section=raw_section, title=title[:100], body=body)


def list_campaign_forums(guild: discord.Guild) -> list[discord.ForumChannel]:
    category = find_campaign_category(guild)
    if category is None:
        return []
    forums = [
        channel
        for channel in category.channels
        if isinstance(channel, discord.ForumChannel)
    ]
    forums.sort(key=lambda forum: forum.position)
    return forums


def match_campaign_forum(
    forums: list[discord.ForumChannel],
    query: str,
) -> discord.ForumChannel | None:
    needle = normalize_section_key(query)
    if not needle:
        return None

    exact: list[discord.ForumChannel] = []
    partial: list[discord.ForumChannel] = []
    folded_query = query.strip().casefold()
    for forum in forums:
        key = normalize_section_key(forum.name)
        if key == needle or forum.name.casefold() == folded_query:
            exact.append(forum)
        elif needle in key or key in needle:
            partial.append(forum)

    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    if len(partial) == 1:
        return partial[0]
    return None


def format_forum_list(forums: list[discord.ForumChannel]) -> str:
    if not forums:
        return "No forum channels in the CAMPAIGN category yet."
    return ", ".join(f"**{forum.name}**" for forum in forums)


def require_campaign_category(guild: discord.Guild) -> discord.CategoryChannel:
    category = find_campaign_category(guild)
    if category is None:
        raise CampaignForumError(
            "No CAMPAIGN category found. The bot will recreate it on the next startup if it has Manage Channels."
        )
    return category


def has_manage_channels(guild: discord.Guild) -> bool:
    me = guild.me
    return bool(me and me.guild_permissions.manage_channels)


def is_campaign_home_guild(guild: discord.Guild) -> bool:
    home_id = app_config.CAMPAIGN_GUILD_ID
    if home_id is not None:
        return guild.id == home_id
    return find_campaign_category(guild) is not None


def require_manage_channels(guild: discord.Guild) -> None:
    if not has_manage_channels(guild):
        raise CampaignForumError("I need the **Manage Channels** permission to create campaign forums.")


def _visible_overwrite(*, manage: bool = False) -> discord.PermissionOverwrite:
    kwargs: dict[str, bool] = {
        "view_channel": True,
        "send_messages": True,
        "send_messages_in_threads": True,
        "create_public_threads": True,
        "create_private_threads": True,
        "read_message_history": True,
        "attach_files": True,
        "embed_links": True,
        "add_reactions": True,
        "use_external_emojis": True,
    }
    if manage:
        kwargs.update(
            manage_threads=True,
            manage_channels=True,
            manage_messages=True,
        )
    return discord.PermissionOverwrite(**kwargs)


def add_staff_channel_overwrites(
    guild: discord.Guild,
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite],
    visibility: discord.PermissionOverwrite,
    *,
    include_admin_roles: bool = True,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    me = guild.me
    me_id = getattr(me, "id", None) if me is not None else None
    owner = guild.owner
    if owner is None:
        owner_id = getattr(guild, "owner_id", None)
        if owner_id is not None and owner_id != me_id:
            owner = discord.Object(id=owner_id)
    if owner is not None and getattr(owner, "id", None) != me_id:
        overwrites[owner] = visibility
    if not include_admin_roles:
        return overwrites
    for role in guild.roles:
        if role == guild.default_role:
            continue
        is_default = getattr(role, "is_default", None)
        is_bot_managed = getattr(role, "is_bot_managed", None)
        if callable(is_default) and is_default():
            continue
        if callable(is_bot_managed) and is_bot_managed():
            continue
        perms = getattr(role, "permissions", None)
        if perms is None:
            continue
        if perms.administrator or perms.manage_guild:
            overwrites[role] = visibility
    return overwrites


def campaign_category_overwrites(
    guild: discord.Guild,
    *,
    include_admin_roles: bool = True,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
    }
    me = guild.me
    if me is not None:
        overwrites[me] = _visible_overwrite(manage=True)
    return add_staff_channel_overwrites(
        guild,
        overwrites,
        _visible_overwrite(),
        include_admin_roles=include_admin_roles,
    )


def _may_persist_campaign_home(guild: discord.Guild) -> bool:
    home_id = app_config.CAMPAIGN_GUILD_ID
    return home_id is None or home_id == guild.id


def _persist_campaign_home(guild: discord.Guild, category_id: int) -> None:
    if _may_persist_campaign_home(guild):
        app_config.set_campaign_category_id(category_id, guild_id=guild.id)


async def ensure_campaign_category(guild: discord.Guild) -> discord.CategoryChannel:
    existing = find_campaign_category(guild)
    if existing is not None:
        if (
            app_config.CAMPAIGN_CATEGORY_ID != existing.id
            or app_config.CAMPAIGN_GUILD_ID != guild.id
        ):
            _persist_campaign_home(guild, existing.id)
        return existing

    require_manage_channels(guild)
    name = app_config.CAMPAIGN_CATEGORY_NAME
    reason = "Recreate missing private CAMPAIGN category"
    try:
        created = await guild.create_category(
            name,
            overwrites=campaign_category_overwrites(guild),
            reason=reason,
        )
    except (discord.Forbidden, discord.HTTPException) as exc:
        logger.warning(
            "Admin overwrites failed for CAMPAIGN in %s: %s. Retrying with bot-only privacy.",
            guild.name,
            exc,
        )
        created = await guild.create_category(
            name,
            overwrites=campaign_category_overwrites(guild, include_admin_roles=False),
            reason=reason,
        )
    _persist_campaign_home(guild, created.id)
    logger.info("Recreated private CAMPAIGN category in %s (%s).", guild.name, created.id)
    return created


def starter_content(*, title: str, body: str) -> str:
    if body.strip():
        return body.strip()[:2000]
    return f"**{title}**\n\n_Fiche à compléter._"


def post_jump_markdown(*, title: str, url: str) -> str:
    return markdown_channel_link(label=title, url=url)


async def ensure_campaign_forum(guild: discord.Guild, name: str) -> discord.ForumChannel:
    existing = match_campaign_forum(list_campaign_forums(guild), name)
    if existing is not None:
        return existing
    require_manage_channels(guild)
    category = await ensure_campaign_category(guild)
    return await guild.create_forum(
        format_forum_channel_name(name),
        category=category,
        reason="Campaign wiki import",
    )


async def ensure_default_campaign_forums(guild: discord.Guild) -> list[discord.ForumChannel]:
    home_id = app_config.CAMPAIGN_GUILD_ID
    if home_id is not None and home_id != guild.id:
        return list_campaign_forums(guild)

    existing = find_campaign_category(guild)
    if existing is None:
        if not has_manage_channels(guild):
            logger.warning(
                "Skipping campaign setup in %s: no CAMPAIGN category and no Manage Channels.",
                guild.name,
            )
            return []
    await ensure_campaign_category(guild)
    forums: list[discord.ForumChannel] = []
    for name in DEFAULT_CAMPAIGN_FORUMS:
        existing = match_campaign_forum(list_campaign_forums(guild), name)
        if existing is not None:
            forums.append(existing)
            continue
        forums.append(await ensure_campaign_forum(guild, name))
        await asyncio.sleep(0.4)
    return forums


def find_existing_thread(
    forums: list[discord.ForumChannel],
    title: str,
) -> discord.Thread | None:
    needle = title.casefold().strip()
    if not needle:
        return None
    for forum in forums:
        for thread in forum.threads:
            if thread.name.casefold() == needle:
                return thread
    return None


async def locate_campaign_thread(
    forums: list[discord.ForumChannel],
    title: str,
) -> discord.Thread | None:
    found = find_existing_thread(forums, title)
    if found is not None:
        return found
    needle = title.casefold().strip()
    if not needle:
        return None
    for forum in forums:
        archived = getattr(forum, "archived_threads", None)
        if not callable(archived):
            continue
        try:
            async for thread in archived(limit=100):
                if thread.name.casefold() == needle:
                    return thread
        except (TypeError, discord.HTTPException, discord.ClientException):
            continue
    return None


_ARCHIVED_PAGE = 100


async def iter_forum_threads(forum: discord.ForumChannel) -> list[discord.Thread]:
    seen: dict[int, discord.Thread] = {thread.id: thread for thread in forum.threads}
    archived = getattr(forum, "archived_threads", None)
    if not callable(archived):
        return list(seen.values())
    before: discord.Thread | None = None
    while True:
        batch: list[discord.Thread] = []
        try:
            kwargs: dict = {"limit": _ARCHIVED_PAGE}
            if before is not None:
                kwargs["before"] = before
            async for thread in archived(**kwargs):
                batch.append(thread)
        except (TypeError, discord.HTTPException, discord.ClientException):
            break
        if not batch:
            break
        for thread in batch:
            seen.setdefault(thread.id, thread)
        if len(batch) < _ARCHIVED_PAGE:
            break
        before = batch[-1]
    return list(seen.values())
