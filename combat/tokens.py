from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from combat.monster_sheet import display_monster_name
from combat.storage import CombatState
from data import DATA_DIR
from srd.fivetools.images import monster_token_url

TOKEN_DIR = DATA_DIR / "monster_tokens"
MAX_TOKEN_BYTES = 4 * 1024 * 1024


def _token_path(name: str) -> Path:
    safe = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in display_monster_name(name)
    )
    return TOKEN_DIR / f"{safe or 'monster'}.webp"


def cache_monster_token(name: str) -> Path | None:
    path = _token_path(name)
    if path.is_file():
        return path
    url = monster_token_url(
        {
            "name": display_monster_name(name),
            "source": "XMM",
            "hasToken": True,
        }
    )
    if not url:
        return None
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Arkann-token/1.0"}
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            data = response.read(MAX_TOKEN_BYTES + 1)
        if not data or len(data) > MAX_TOKEN_BYTES:
            return None
        with Image.open(io.BytesIO(data)) as opened:
            converted = opened.convert("RGBA")
        TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        converted.save(path, format="WEBP")
        return path
    except (OSError, ValueError, TimeoutError, urllib.error.URLError):
        return None


def load_monster_token(name: str, *, fetch: bool = False) -> Image.Image | None:
    path = _token_path(name)
    if not path.is_file() and fetch:
        path = cache_monster_token(name)
    if path is None or not path.is_file():
        return None
    try:
        with Image.open(path) as opened:
            return opened.convert("RGBA")
    except OSError:
        return None


def prefetch_monster_tokens(state: CombatState) -> None:
    for combatant in state.combatants.values():
        if combatant.user_id is None:
            cache_monster_token(combatant.name)
