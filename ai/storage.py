from data.db import get_json, set_json

CONTEXT_LIMIT = 2000


def context_key(guild_id: int, channel_id: int) -> str:
    return f"ai_context:{guild_id}:{channel_id}"


def get_ai_context(*, guild_id: int, channel_id: int) -> str:
    raw = get_json(context_key(guild_id, channel_id))
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        return str(raw.get("text") or "").strip()
    return ""


def save_ai_context(*, guild_id: int, channel_id: int, text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) > CONTEXT_LIMIT:
        cleaned = cleaned[: CONTEXT_LIMIT - 1].rstrip() + "…"
    set_json(context_key(guild_id, channel_id), cleaned)
    return cleaned


def clear_ai_context(*, guild_id: int, channel_id: int) -> None:
    set_json(context_key(guild_id, channel_id), "")
