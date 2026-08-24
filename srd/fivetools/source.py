from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from srd.fivetools.edition import include_official_item

# Keys consumed by loader.FiveToolsIndex._ingest_brew_body
LOADER_LIST_KEYS = (
    "itemProperty",
    "spell",
    "race",
    "class",
    "classFeature",
    "subclass",
    "subclassFeature",
    "background",
    "feat",
    "condition",
    "skill",
    "baseitem",
    "item",
    "monster",
)

GLOB_SOURCES = (
    ("spells/*.json", ("spell",)),
    ("class/*.json", ("class", "classFeature", "subclass", "subclassFeature")),
)

FILE_SOURCES = (
    ("races.json", ("race",)),
    ("backgrounds.json", ("background",)),
    ("feats.json", ("feat",)),
    ("conditionsdiseases.json", ("condition",)),
    ("skills.json", ("skill",)),
    ("items-base.json", ("baseitem", "itemProperty")),
    ("items.json", ("item",)),
    ("bestiary/bestiary-xmm.json", ("monster",)),
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _extend(target: dict[str, list[Any]], key: str, values: list[Any]) -> None:
    kept = [item for item in values if include_official_item(item)]
    if kept:
        target.setdefault(key, []).extend(kept)


def _collect_sources(body: dict[str, Any]) -> list[dict[str, str]]:
    codes: set[str] = set()
    for key in LOADER_LIST_KEYS:
        for item in body.get(key, []):
            source = item.get("source")
            if source:
                codes.add(str(source))
    return [
        {"json": code, "abbreviation": code, "full": code} for code in sorted(codes)
    ]


def build_official_body(data_dir: Path) -> dict[str, Any]:
    body: dict[str, list[Any]] = {}

    for pattern, keys in GLOB_SOURCES:
        for path in sorted(data_dir.glob(pattern)):
            payload = load_json(path)
            for key in keys:
                _extend(body, key, payload.get(key, []))

    for filename, keys in FILE_SOURCES:
        path = data_dir / filename
        if not path.is_file():
            continue
        payload = load_json(path)
        for key in keys:
            _extend(body, key, payload.get(key, []))

    now = int(time.time())
    return {
        "_meta": {
            "sources": _collect_sources(body),
            "edition": "mixed",
            "dateAdded": now,
            "dateLastModified": now,
        },
        **body,
    }


def summarize_body(body: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in LOADER_LIST_KEYS:
        count = len(body.get(key, []))
        if count:
            parts.append(f"{key}={count}")
    return ", ".join(parts)
