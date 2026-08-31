from dataclasses import dataclass, field
from typing import Any

import discord

from data.db import get_json, set_json

SCENE_COLOR = 0x9B59B6
_SCENE_SEPARATORS = ("--", "—", "–")


@dataclass
class SceneState:
    title: str = ""
    mood: str = ""
    note: str = ""
    present: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "mood": self.mood,
            "note": self.note,
            "present": dict(self.present),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SceneState":
        if not isinstance(data, dict):
            return cls()
        raw_present = data.get("present") or {}
        present: dict[str, str] = {}
        if isinstance(raw_present, dict):
            for key, value in raw_present.items():
                name = str(value or "").strip()
                if name:
                    present[str(key)] = name
        return cls(
            title=str(data.get("title") or "").strip(),
            mood=str(data.get("mood") or "").strip(),
            note=str(data.get("note") or "").strip(),
            present=present,
        )


def scene_key(guild_id: int, channel_id: int) -> str:
    return f"scene:{guild_id}:{channel_id}"


def get_scene(*, guild_id: int, channel_id: int) -> SceneState:
    return SceneState.from_dict(get_json(scene_key(guild_id, channel_id)))


def save_scene(*, guild_id: int, channel_id: int, scene: SceneState) -> None:
    set_json(scene_key(guild_id, channel_id), scene.to_dict())


def parse_scene_set(text: str) -> tuple[str, str | None]:
    cleaned = text.strip()
    if not cleaned:
        return "", None
    for separator in _SCENE_SEPARATORS:
        if separator in cleaned:
            left, right = cleaned.split(separator, 1)
            return left.strip(), right.strip()
    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        return left.strip(), right.strip()
    return cleaned, None


def mark_present(
    *,
    guild_id: int,
    channel_id: int,
    user_id: int,
    name: str,
) -> SceneState:
    scene = get_scene(guild_id=guild_id, channel_id=channel_id)
    scene.present[str(user_id)] = name.strip()
    save_scene(guild_id=guild_id, channel_id=channel_id, scene=scene)
    return scene


def mark_absent(*, guild_id: int, channel_id: int, user_id: int) -> SceneState:
    scene = get_scene(guild_id=guild_id, channel_id=channel_id)
    scene.present.pop(str(user_id), None)
    save_scene(guild_id=guild_id, channel_id=channel_id, scene=scene)
    return scene


def present_names(scene: SceneState) -> list[str]:
    return sorted(scene.present.values(), key=str.casefold)


def build_scene_embed(
    scene: SceneState,
    *,
    clock_line: str | None = None,
    prefix: str = ";",
) -> discord.Embed:
    title = scene.title or "Scène"
    embed = discord.Embed(title=f"🎭 {title}", color=SCENE_COLOR)
    if scene.mood:
        embed.description = scene.mood
    elif not scene.title:
        embed.description = (
            f"Aucune scène posée. `{prefix}scene set La taverne -- feu de cheminée`"
        )
    names = present_names(scene)
    embed.add_field(
        name="👥 Présents",
        value=", ".join(f"**{name}**" for name in names)
        if names
        else "*Personne n’a annoncé son arrivée.*",
        inline=False,
    )
    if scene.note:
        embed.add_field(name="📝 Note", value=scene.note, inline=False)
    if clock_line:
        embed.add_field(name="⏳ Temps", value=clock_line, inline=False)
    embed.set_footer(
        text=f"{prefix}arrive · {prefix}leave · {prefix}scene set <titre> -- <ambiance>"
    )
    return embed
