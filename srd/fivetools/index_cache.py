"""On-disk cache of the built 5etools index.

Parsing the 56 MB homebrew export peaks above 500 MB of RAM; unpickling the
finished index needs about a quarter of that and is five times faster. The
cache key covers the 5etools files and the code that builds the index, so any
change to either rebuilds it.
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Any

from data import DATA_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR / "cache"
_PREFIX = "fivetools-index-"
# Modules whose code shapes the pickled index.
_BUILDER_FILES = ("loader.py", "source.py", "edition.py", "images.py", "paths.py")


def _code_fingerprint() -> str:
    digest = hashlib.sha256()
    here = Path(__file__).resolve().parent
    for name in _BUILDER_FILES:
        path = here / name
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def cache_path(content_fingerprint: str) -> Path:
    return CACHE_DIR / f"{_PREFIX}{content_fingerprint}-{_code_fingerprint()}.pkl"


def load_cached_index(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            return pickle.load(handle)
    except Exception:
        logger.warning(
            "Ignoring unreadable 5etools index cache %s", path, exc_info=True
        )
        return None


def save_cached_index(path: Path, index: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("wb") as handle:
            pickle.dump(index, handle, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        for stale in CACHE_DIR.glob(f"{_PREFIX}*.pkl"):
            if stale != path:
                stale.unlink(missing_ok=True)
    except Exception:
        logger.warning("Could not write the 5etools index cache", exc_info=True)
