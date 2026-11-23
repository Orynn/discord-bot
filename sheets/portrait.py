from __future__ import annotations

import io
import ipaddress
import socket
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


def _is_public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    return ip.is_global and not ip.is_multicast


def _is_local_hostname(host: str) -> bool:
    lowered = host.casefold().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".localhost", ".local")):
        return True
    try:
        ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return not _is_public_ip(lowered)


def _host_resolves_publicly(host: str) -> bool:
    """True only when every address the host resolves to is public."""
    if _is_local_hostname(host):
        return False
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(_is_public_ip(address) for address in addresses)


class _PublicOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    # A public URL must not be able to bounce the bot onto an internal host.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.scheme not in {"http", "https"} or not _host_resolves_publicly(
            target.hostname or ""
        ):
            raise urllib.error.URLError("Redirect to a non-public address refused.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_PublicOnlyRedirectHandler)


def parse_image_url(text: str) -> str:
    cleaned = text.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Need an http(s) image URL, or attach a picture.")
    if _is_local_hostname(parsed.hostname):
        raise ValueError(
            "Cette adresse n’est pas publique : utilise une image en ligne."
        )
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
    """Blocking download; call it through asyncio.to_thread from the bot."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _host_resolves_publicly(
        parsed.hostname or ""
    ):
        return None
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Arkann-portrait/1.0"}
        )
        with _OPENER.open(request, timeout=4) as response:
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
