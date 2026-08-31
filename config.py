import json
import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")

_CONFIG_PATH = _ROOT / "config.json"

_DEFAULT_CONFIG: dict = {
    "prefix": ";",
    "catchup_enabled": True,
    "catchup_max_messages": 200,
    "catchup_max_age_hours": 72,
    "campaign_category_id": 1186287629302501429,
    "campaign_category_name": "CAMPAIGN",
    "home_guild_name": "Potato Head",
    "campaign_cache_ttl_seconds": 900,
    "campaign_messages_per_thread": 20,
    "fivetools_root": "5etools",
    "fivetools_data_dir": "5etools/data",
    "fivetools_export_file": "5etools/5etools.json",
    "fivetools_homebrew_file": "5etools/homebrew.json",
    "fivetools_file": "5etools/5etools.json",
    "player_category_width": 25,
    "player_category_emoji": "🐉",
    "player_channel_ooc": "📢blabla",
    "player_channel_rp": "🎲roleplay",
    "staff_usernames": ["Orynn"],
    "image_provider": "auto",
    "image_local_url": "http://127.0.0.1:7860",
    "image_model": "flux",
    "image_width": 1024,
    "image_height": 1024,
    "image_timeout_seconds": 180,
    "image_cooldown_seconds": 20,
    "image_history_limit": 1000,
    "editor_host": "0.0.0.0",
    "editor_port": 8765,
    "editor_public_url": "",
}

if _CONFIG_PATH.exists():
    with _CONFIG_PATH.open(mode="r", encoding="utf-8") as file:
        config = json.load(fp=file)
else:
    config = dict(_DEFAULT_CONFIG)

PREFIX = config.get("prefix", _DEFAULT_CONFIG["prefix"])
CATCHUP_ENABLED = config.get("catchup_enabled", _DEFAULT_CONFIG["catchup_enabled"])
CATCHUP_MAX_MESSAGES = config.get(
    "catchup_max_messages", _DEFAULT_CONFIG["catchup_max_messages"]
)
CATCHUP_MAX_AGE_HOURS = config.get(
    "catchup_max_age_hours", _DEFAULT_CONFIG["catchup_max_age_hours"]
)

_raw_campaign_id = config.get(
    "campaign_category_id", _DEFAULT_CONFIG["campaign_category_id"]
)
CAMPAIGN_CATEGORY_ID: int | None = int(_raw_campaign_id) if _raw_campaign_id else None
_raw_campaign_guild = config.get("campaign_guild_id")
CAMPAIGN_GUILD_ID: int | None = (
    int(_raw_campaign_guild) if _raw_campaign_guild else None
)
CAMPAIGN_CATEGORY_NAME = str(
    config.get("campaign_category_name", _DEFAULT_CONFIG["campaign_category_name"])
)
_raw_home_guild = config.get("home_guild_id")
HOME_GUILD_ID: int | None = (
    int(_raw_home_guild) if _raw_home_guild else CAMPAIGN_GUILD_ID
)
HOME_GUILD_NAME = str(config.get("home_guild_name", "Potato Head")).strip()


def is_home_guild(guild: object | None) -> bool:
    if guild is None:
        return True
    guild_id = getattr(guild, "id", None)
    home_id = HOME_GUILD_ID if HOME_GUILD_ID is not None else CAMPAIGN_GUILD_ID
    if home_id is not None and guild_id is not None:
        return int(guild_id) == int(home_id)
    name = getattr(guild, "name", None)
    if HOME_GUILD_NAME and name:
        return str(name).casefold() == HOME_GUILD_NAME.casefold()
    return True
CAMPAIGN_CACHE_TTL_SECONDS = int(
    config.get(
        "campaign_cache_ttl_seconds", _DEFAULT_CONFIG["campaign_cache_ttl_seconds"]
    )
)
CAMPAIGN_MESSAGES_PER_THREAD = int(
    config.get(
        "campaign_messages_per_thread", _DEFAULT_CONFIG["campaign_messages_per_thread"]
    )
)


def _resolve_path(key: str, *, fallback: str | None = None) -> Path:
    value = config.get(
        key, fallback if fallback is not None else _DEFAULT_CONFIG.get(key)
    )
    return _ROOT / str(value)


FIVETOOLS_ROOT = _resolve_path("fivetools_root", fallback="5etools")
FIVETOOLS_DATA_DIR = _resolve_path("fivetools_data_dir", fallback="5etools/data")
if "fivetools_export_file" in config:
    FIVETOOLS_EXPORT_FILE = _resolve_path("fivetools_export_file")
elif "fivetools_file" in config:
    FIVETOOLS_EXPORT_FILE = _ROOT / str(config["fivetools_file"])
else:
    FIVETOOLS_EXPORT_FILE = _resolve_path(
        "fivetools_export_file", fallback="5etools/5etools.json"
    )
FIVETOOLS_HOMEBREW_FILE = _resolve_path(
    "fivetools_homebrew_file", fallback="5etools/homebrew.json"
)

# Legacy alias used by glossary fingerprinting and startup logs.
FIVETOOLS_FILE = FIVETOOLS_EXPORT_FILE

_raw_token = os.environ.get("DISCORD_TOKEN")
TOKEN: str | None = None if not _raw_token or _raw_token == "TOKEN_HERE" else _raw_token


def require_token() -> str:
    if TOKEN is None:
        raise ValueError("Set DISCORD_TOKEN in .env (see .env.example)")
    return TOKEN


def set_campaign_category_id(category_id: int, *, guild_id: int | None = None) -> None:
    global CAMPAIGN_CATEGORY_ID, CAMPAIGN_GUILD_ID
    CAMPAIGN_CATEGORY_ID = int(category_id)
    config["campaign_category_id"] = CAMPAIGN_CATEGORY_ID
    if guild_id is not None:
        CAMPAIGN_GUILD_ID = int(guild_id)
        config["campaign_guild_id"] = CAMPAIGN_GUILD_ID
    with _CONFIG_PATH.open(mode="w", encoding="utf-8") as file:
        json.dump(config, file, indent=2, ensure_ascii=False)
        file.write("\n")


PLAYER_CATEGORY_WIDTH = int(
    config.get("player_category_width", _DEFAULT_CONFIG["player_category_width"])
)
PLAYER_CATEGORY_EMOJI = str(
    config.get("player_category_emoji", _DEFAULT_CONFIG["player_category_emoji"])
)
PLAYER_CHANNEL_OOC = str(
    config.get("player_channel_ooc", _DEFAULT_CONFIG["player_channel_ooc"])
)
PLAYER_CHANNEL_RP = str(
    config.get("player_channel_rp", _DEFAULT_CONFIG["player_channel_rp"])
)
STAFF_USERNAMES = [
    str(name).casefold()
    for name in config.get("staff_usernames", ["Orynn"])
    if str(name).strip()
]
STAFF_USER_IDS = {
    int(user_id) for user_id in config.get("staff_user_ids", []) if str(user_id).strip()
}

IMAGE_PROVIDER = str(config.get("image_provider", _DEFAULT_CONFIG["image_provider"]))
IMAGE_LOCAL_URL = str(config.get("image_local_url", _DEFAULT_CONFIG["image_local_url"]))
IMAGE_MODEL = str(config.get("image_model", _DEFAULT_CONFIG["image_model"]))
IMAGE_WIDTH = int(config.get("image_width", _DEFAULT_CONFIG["image_width"]))
IMAGE_HEIGHT = int(config.get("image_height", _DEFAULT_CONFIG["image_height"]))
IMAGE_TIMEOUT_SECONDS = int(
    config.get("image_timeout_seconds", _DEFAULT_CONFIG["image_timeout_seconds"])
)
IMAGE_COOLDOWN_SECONDS = int(
    config.get("image_cooldown_seconds", _DEFAULT_CONFIG["image_cooldown_seconds"])
)
IMAGE_HISTORY_LIMIT = int(
    config.get("image_history_limit", _DEFAULT_CONFIG["image_history_limit"])
)
EDITOR_HOST = str(
    os.environ.get("ARKANN_EDITOR_HOST")
    or config.get("editor_host", _DEFAULT_CONFIG["editor_host"])
)
EDITOR_PORT = int(
    os.environ.get("ARKANN_EDITOR_PORT")
    or config.get("editor_port", _DEFAULT_CONFIG["editor_port"])
)
EDITOR_PUBLIC_URL = str(
    os.environ.get("ARKANN_EDITOR_URL")
    or config.get("editor_public_url", "")
    or ""
).strip()
