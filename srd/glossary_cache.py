from dataclasses import asdict
from pathlib import Path
from typing import Any

from data.db import get_json, set_json

CACHE_KEY = "srd_glossary_v5_monsters"


def file_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def save_glossary(entries: list[Any], *, fingerprint: str) -> None:
    payload = {
        "fingerprint": fingerprint,
        "entries": [asdict(entry) for entry in entries],
    }
    set_json(CACHE_KEY, payload)


def load_glossary(*, fingerprint: str) -> list[dict[str, Any]] | None:
    cached = get_json(CACHE_KEY)
    if not isinstance(cached, dict):
        return None
    if cached.get("fingerprint") != fingerprint:
        return None
    entries = cached.get("entries")
    if not isinstance(entries, list):
        return None
    return entries
