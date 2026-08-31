"""Backward-compatible re-exports. Prefer `from srd.fivetools.loader import …`."""

from srd.fivetools.loader import (
    FiveToolsIndex,
    ensure_index_loaded,
    get_index,
    reload_index,
)

__all__ = ["FiveToolsIndex", "ensure_index_loaded", "get_index", "reload_index"]
