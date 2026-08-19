from __future__ import annotations

import hashlib
from pathlib import Path

from config import (
    FIVETOOLS_DATA_DIR,
    FIVETOOLS_EXPORT_FILE,
    FIVETOOLS_HOMEBREW_FILE,
    FIVETOOLS_ROOT,
)

OFFICIAL_ENTRY_MARKERS = ("5etools-src-official", "5etools-mirror")


def is_official_mirror_entry(entry: dict) -> bool:
    head = entry.get("head") or {}
    filename = str(head.get("filename") or "")
    url = str(head.get("url") or "")
    haystack = f"{filename} {url}".lower()
    return any(marker in haystack for marker in OFFICIAL_ENTRY_MARKERS)


def has_official_source() -> bool:
    return FIVETOOLS_DATA_DIR.is_dir() and any(FIVETOOLS_DATA_DIR.glob("*.json"))


def has_homebrew_source() -> bool:
    return FIVETOOLS_HOMEBREW_FILE.is_file() or FIVETOOLS_EXPORT_FILE.is_file()


def is_available() -> bool:
    return has_official_source() or has_homebrew_source()


def describe_sources() -> str:
    parts: list[str] = []
    if has_official_source():
        parts.append(f"official data ({FIVETOOLS_DATA_DIR})")
    if FIVETOOLS_HOMEBREW_FILE.is_file():
        parts.append(f"homebrew ({FIVETOOLS_HOMEBREW_FILE})")
    elif FIVETOOLS_EXPORT_FILE.is_file():
        parts.append(f"export ({FIVETOOLS_EXPORT_FILE})")
    return ", ".join(parts) if parts else "no 5etools sources configured"


def content_fingerprint() -> str:
    """Fingerprint all inputs that feed the rules index."""
    parts: list[str] = []

    def add_path(path: Path) -> None:
        if not path.is_file():
            return
        stat = path.stat()
        parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")

    if has_official_source():
        parts.append(f"dir:{FIVETOOLS_DATA_DIR}")
        for path in sorted(FIVETOOLS_DATA_DIR.rglob("*.json")):
            stat = path.stat()
            rel = path.relative_to(FIVETOOLS_ROOT)
            parts.append(f"{rel}:{stat.st_mtime_ns}:{stat.st_size}")

    add_path(FIVETOOLS_HOMEBREW_FILE)
    add_path(FIVETOOLS_EXPORT_FILE)

    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]
