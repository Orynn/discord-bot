from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from srd.fivetools.source import build_official_body, load_json, summarize_body

REPO_URL = "https://github.com/5etools-mirror-3/5etools-src.git"


def _entry_from_body(body: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    checksum = hashlib.md5(serialized).hexdigest()
    return {
        "head": {
            "docIdLocal": str(uuid.uuid4()),
            "timeAdded": int(time.time() * 1000),
            "checksum": checksum,
            "url": REPO_URL,
            "filename": "5etools-src-official.json",
            "isLocal": True,
            "isEditable": False,
        },
        "body": body,
    }


def _read_site_version(merge_path: Path | None) -> str:
    if merge_path and merge_path.is_file():
        export = load_json(merge_path)
        return str(export.get("siteVersion", "unknown"))
    return "unknown"


def build_export(data_dir: Path, *, merge_path: Path | None) -> dict[str, Any]:
    official_entry = _entry_from_body(build_official_body(data_dir))

    homebrew_entries: list[dict[str, Any]] = []
    sync_metas: list[Any] = []
    sync_style: dict[str, Any] = {}

    if merge_path and merge_path.is_file():
        existing = load_json(merge_path)
        async_block = existing.get("async") or {}
        homebrew_entries = list(async_block.get("HOMEBREW_2_STORAGE") or [])
        sync_metas = list(
            existing.get("sync", {}).get("HOMEBREW_2_STORAGE_METAS") or []
        )
        sync_style = dict(existing.get("syncStyle") or {})

    return {
        "fileType": "5etools",
        "siteVersion": _read_site_version(merge_path),
        "sync": {"HOMEBREW_2_STORAGE_METAS": sync_metas},
        "async": {
            "HOMEBREW_2_STORAGE": [official_entry, *homebrew_entries],
        },
        "syncStyle": sync_style,
    }


def extract_homebrew_export(source: Path) -> dict[str, Any]:
    """Extract homebrew-only entries from a merged 5e.tools export."""
    from srd.fivetools.paths import is_official_mirror_entry

    export = load_json(source)
    entries = export.get("async", {}).get("HOMEBREW_2_STORAGE") or []
    homebrew = [entry for entry in entries if not is_official_mirror_entry(entry)]
    return {
        "fileType": "5etools",
        "siteVersion": export.get("siteVersion", "unknown"),
        "sync": export.get("sync") or {"HOMEBREW_2_STORAGE_METAS": []},
        "async": {"HOMEBREW_2_STORAGE": homebrew},
        "syncStyle": export.get("syncStyle") or {},
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent="\t")
        handle.write("\n")


def summarize_export(export: dict[str, Any]) -> str:
    entries = export.get("async", {}).get("HOMEBREW_2_STORAGE") or []
    if not entries:
        return "empty export"
    first_body = entries[0].get("body") or {}
    return summarize_body(first_body)
