from __future__ import annotations

from typing import Any
from urllib.parse import quote

FIVETOOLS_IMG = "https://5e.tools/img"


def media_url(path: str) -> str:
    parts = [quote(part, safe="") for part in path.strip("/").split("/") if part]
    return f"{FIVETOOLS_IMG}/{'/'.join(parts)}"


def image_href_url(entry: dict[str, Any]) -> str | None:
    href = entry.get("href")
    if not isinstance(href, dict):
        return None
    kind = href.get("type")
    if kind == "external":
        url = href.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            return url
        return None
    if kind == "internal":
        path = href.get("path")
        if isinstance(path, str) and path.strip():
            return media_url(path)
    return None


def first_image_url(images: Any) -> str | None:
    if not isinstance(images, list):
        return None
    for entry in images:
        if not isinstance(entry, dict):
            continue
        url = image_href_url(entry)
        if url:
            return url
    return None


def monster_token_url(item: dict[str, Any]) -> str | None:
    legacy = item.get("tokenUrl")
    if isinstance(legacy, str) and legacy.startswith(("http://", "https://")):
        return legacy
    token_href = item.get("tokenHref")
    if isinstance(token_href, dict):
        return image_href_url({"href": token_href})
    token = item.get("token")
    if isinstance(token, dict):
        name = str(token.get("name") or item.get("name") or "")
        source = str(token.get("source") or item.get("source") or "XMM")
    elif item.get("hasToken"):
        name = str(item.get("name") or "")
        source = str(item.get("source") or "XMM")
    else:
        return None
    if not name:
        return None
    safe_name = name.replace('"', "")
    return media_url(f"bestiary/tokens/{source}/{safe_name}.webp")
