from campaign.clock import CampaignTime
from data.db import get_json, set_json


def _player_key(guild_id: int, user_id: int) -> str:
    return f"campaign_clock:{guild_id}:{user_id}"


def _legacy_key(guild_id: int) -> str:
    return f"campaign_clock:{guild_id}"


def get_clock(guild_id: int, user_id: int) -> CampaignTime:
    data = get_json(_player_key(guild_id, user_id))
    if data is None and user_id >= 0:
        data = get_json(_legacy_key(guild_id))
    return CampaignTime.from_dict(data)


def save_clock(
    guild_id: int,
    user_id: int,
    clock: CampaignTime,
    *,
    update_default: bool = False,
) -> None:
    payload = clock.to_dict()
    set_json(_player_key(guild_id, user_id), payload)
    if update_default:
        set_json(_legacy_key(guild_id), payload)
