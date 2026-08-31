from __future__ import annotations

from typing import Any

# 2014 Player's Handbook — excluded from bundled official data; use XPHB instead.
EXCLUDED_OFFICIAL_SOURCES = frozenset({"PHB"})

# Other 2014 core rulebooks — deprioritized when a 2024 entry exists for the same name.
LEGACY_2014_SOURCES = frozenset({"PHB", "DMG", "MM", "SRD"})

# 2024 core rulebooks (explicit; do not use startswith — XGE/TCE are 2014).
CORE_2024_SOURCES = frozenset({"XPHB", "XMM", "XDMG"})


def edition_rank(item: dict[str, Any]) -> int:
    """Higher rank wins name collisions. Prefer 2024 / XPHB over 2014 / PHB."""
    if item.get("edition") == "one":
        return 4
    if item.get("basicRules2024") or item.get("srd52"):
        return 3

    source = str(item.get("source") or "")
    if source in CORE_2024_SOURCES:
        return 3
    if source.endswith("24"):
        return 2
    if source in LEGACY_2014_SOURCES:
        return 0
    return 1


def should_replace(existing: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    if existing is None:
        return True
    new_rank = edition_rank(candidate)
    old_rank = edition_rank(existing)
    if new_rank != old_rank:
        return new_rank > old_rank
    return True


def include_official_item(item: dict[str, Any]) -> bool:
    """Drop PHB entries from bundled official JSON — bot uses XPHB for 2024 rules."""
    return str(item.get("source") or "") not in EXCLUDED_OFFICIAL_SOURCES


def _parse_reprint_tag(tag: str) -> tuple[str, str] | None:
    if "|" not in tag:
        return None
    name, source = tag.rsplit("|", 1)
    name = name.strip()
    source = source.strip()
    if name and source:
        return name, source
    return None


_URL_SOURCE_ALIASES = {"PHB": "XPHB", "MM": "XMM"}


def url_source(source: str | None) -> str:
    """Map legacy core-book codes to 2024 5e.tools URL anchors."""
    code = str(source or "XPHB")
    return _URL_SOURCE_ALIASES.get(code, code)


def url_target(item: dict[str, Any]) -> tuple[str, str]:
    """Return the (name, source) pair used in 5e.tools URL anchors."""
    name = str(item["name"])
    source = str(item.get("source") or "XPHB")

    if source in EXCLUDED_OFFICIAL_SOURCES:
        for tag in item.get("reprintedAs") or []:
            parsed = _parse_reprint_tag(str(tag))
            if parsed and parsed[1] in CORE_2024_SOURCES:
                return parsed
        return name, "XPHB"

    return name, url_source(source)
