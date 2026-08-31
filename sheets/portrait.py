from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import discord
from PIL import Image

from data import DATA_DIR

PORTRAIT_DIR = DATA_DIR / "portraits"
PORTRAIT_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
MAX_PORTRAIT_BYTES = 8 * 1024 * 1024
CLEAR_WORDS = frozenset({"clear", "none", "remove", "delete", "off", "reset"})


def is_image_attachment(attachment: discord.Attachment) -> bool:
    content = (attachment.content_type or "").split(";", 1)[0].strip().casefold()
    if content.startswith("image/"):
        return True
    name = (attachment.filename or "").casefold()
    return name.endswith(PORTRAIT_SUFFIXES)


def parse_image_url(text: str) -> str:
    cleaned = text.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Need an http(s) image URL, or attach a picture.")
    return cleaned


def portrait_path(*, guild_id: int, user_id: int) -> Path | None:
    for suffix in PORTRAIT_SUFFIXES:
        path = PORTRAIT_DIR / f"{guild_id}_{user_id}{suffix}"
        if path.is_file():
            return path
    return None


def load_portrait_image(
    *,
    guild_id: int,
    user_id: int,
    image_url: str = "",
    fetch_url: bool = False,
) -> Image.Image | None:
    path = portrait_path(guild_id=guild_id, user_id=user_id)
    if path is None and fetch_url and image_url:
        path = cache_portrait_from_url(
            guild_id=guild_id, user_id=user_id, url=image_url
        )
    if path is None:
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except OSError:
        return None


def cache_portrait_from_url(
    *,
    guild_id: int,
    user_id: int,
    url: str,
) -> Path | None:
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Arkann-portrait/1.0"}
        )
        with urllib.request.urlopen(request, timeout=4) as response:
            data = response.read(MAX_PORTRAIT_BYTES + 1)
        if not data or len(data) > MAX_PORTRAIT_BYTES:
            return None
        with Image.open(io.BytesIO(data)) as opened:
            converted = opened.convert("RGBA")
        PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
        clear_portrait_file(guild_id=guild_id, user_id=user_id)
        path = PORTRAIT_DIR / f"{guild_id}_{user_id}.png"
        converted.save(path, format="PNG")
        return path
    except (OSError, ValueError, TimeoutError, urllib.error.URLError):
        return None


def clear_portrait_file(*, guild_id: int, user_id: int) -> None:
    for suffix in PORTRAIT_SUFFIXES:
        path = PORTRAIT_DIR / f"{guild_id}_{user_id}{suffix}"
        if path.is_file():
            path.unlink()


def apply_sheet_portrait(
    embed: discord.Embed,
    *,
    image_url: str,
    attachment_name: str | None = None,
) -> None:
    if attachment_name:
        embed.set_thumbnail(url=f"attachment://{attachment_name}")
        return
    if image_url:
        embed.set_thumbnail(url=image_url)


async def save_portrait_attachment(
    attachment: discord.Attachment,
    *,
    guild_id: int,
    user_id: int,
) -> Path:
    if not is_image_attachment(attachment):
        raise ValueError("Attach a picture (png, jpg, webp or gif).")
    if attachment.size and attachment.size > MAX_PORTRAIT_BYTES:
        raise ValueError("Portrait must be 8 MB or smaller.")
    suffix = Path(attachment.filename or "portrait.png").suffix.casefold()
    if suffix not in PORTRAIT_SUFFIXES:
        suffix = ".png"
    PORTRAIT_DIR.mkdir(parents=True, exist_ok=True)
    clear_portrait_file(guild_id=guild_id, user_id=user_id)
    path = PORTRAIT_DIR / f"{guild_id}_{user_id}{suffix}"
    await attachment.save(path)
    return path
