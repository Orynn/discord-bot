from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp

from config import (
    IMAGE_HEIGHT,
    IMAGE_LOCAL_URL,
    IMAGE_MODEL,
    IMAGE_PROVIDER,
    IMAGE_TIMEOUT_SECONDS,
    IMAGE_WIDTH,
)

logger = logging.getLogger(__name__)

STYLE_PREFIX = (
    "Fantasy illustration, Dungeons and Dragons painted concept art, "
    "cinematic lighting, detailed environment, SFW, no nudity, no text, "
    "no watermark, no logo."
)
NEGATIVE_PROMPT = (
    "nsfw, nude, nudity, sexual, watermark, text, logo, blurry, low quality, "
    "modern clothing, photograph"
)
USER_AGENT = "ArkannBot/1.0 (Discord D&D bot; image generation)"
POLLINATIONS_GEN_URL = "https://gen.pollinations.ai/image"
POLLINATIONS_LEGACY_URL = "https://image.pollinations.ai/prompt"
POLLINATIONS_URL = POLLINATIONS_GEN_URL
MAX_PROMPT_CHARS = 1200
MAX_SCENE_LINE_CHARS = 400
MAX_PLACE_CHARS = 80
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_FOCUS_BUDGET = 220
_NOW_BUDGET = 380
_SETTING_BUDGET = 160
_ENVIRONMENT_BUDGET = 280
_CAST_LIMIT = 8
_NOW_BEATS = 14
_SETTING_SNIPPETS = 8

_SPEECH_ACTION = re.compile(
    r"^(?:>>>\s*)?\*\*\*(.+?)\*\*\s+\(([^)]+)\)\*\s*:?\s*(.*)$",
    re.DOTALL,
)
_SPEECH_ONLY = re.compile(
    r"^(?:>>>\s*)?\*{2,3}([^*]+)\*{2,3}\s*:?\s*(.*)$",
    re.DOTALL,
)
_SPEAKER_PREFIX = re.compile(r"^([^:]{1,40}):\s+(.*)$", re.DOTALL)


class ImagePromptError(ValueError):
    """Nothing usable to illustrate."""


class ImageGenerationError(Exception):
    """The image service failed or returned nothing usable."""


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    filename: str
    content_type: str


def unwrap_scene_text(text: str) -> str:
    stripped = text.strip()
    if len(stripped) >= 2 and stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
        stripped = stripped[1:-1].strip()
    if stripped.startswith("||") and stripped.endswith("||") and len(stripped) > 4:
        stripped = stripped[2:-2].strip()
    return stripped


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_command_text(text: str, *, prefix: str) -> bool:
    if text.startswith(prefix):
        return True
    return text.startswith("/") and " " in text[:20]


def _is_bot_rp(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(">>>") or stripped.startswith("***"):
        return True
    return (
        len(stripped) >= 2
        and stripped.startswith("*")
        and stripped.endswith("*")
        and not stripped.startswith("**")
    )


def usable_scene_line(content: str | None, *, prefix: str) -> str | None:
    if not content:
        return None
    text = unwrap_scene_text(content)
    if not text or _is_command_text(text, prefix=prefix):
        return None
    if len(text) < 3:
        return None
    return text[:MAX_SCENE_LINE_CHARS]


def extract_scene_line(
    *,
    content: str | None,
    prefix: str,
    is_bot: bool = False,
    author: str | None = None,
    has_attachments: bool = False,
) -> str | None:
    if not content:
        return None
    raw = content.strip()
    if not raw or _is_command_text(raw, prefix=prefix):
        return None
    if has_attachments and is_bot:
        return None
    if is_bot and not _is_bot_rp(raw):
        return None
    if _is_bot_rp(raw) and ("***" in raw[:80] or raw.startswith(">>>")):
        line = _collapse_ws(raw)
        return line[:500] if len(line) >= 3 else None
    line = usable_scene_line(raw, prefix=prefix)
    if line is None:
        return None
    if author and not is_bot and not line.casefold().startswith(author.casefold()):
        return f"{author}: {line}"[:500]
    return line


def clip_text(text: str, limit: int) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: max(0, limit - 1)].rstrip() + "…"


def clip_text_end(text: str, limit: int) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return "…" + stripped[-(limit - 1) :].lstrip()


def parse_rp_line(line: str) -> tuple[str | None, str | None, str]:
    text = unwrap_scene_text(line)
    text = text.lstrip("> ").strip()
    match = _SPEECH_ACTION.match(text)
    if match:
        return (
            match.group(1).strip(),
            match.group(2).strip() or None,
            _collapse_ws(match.group(3)),
        )
    match = _SPEECH_ONLY.match(text)
    if match:
        return match.group(1).strip(), None, _collapse_ws(match.group(2))
    return None, None, _collapse_ws(text)


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _beat_from_parts(speaker: str, action: str | None, text: str) -> str:
    bits: list[str] = [speaker]
    if action:
        bits.append(action.rstrip("."))
    if text and len(text) <= 90:
        bits.append(f"« {clip_text(text, 90)} »")
    elif text and not action:
        bits.append("speaking")
    return " ".join(bits)


def summarize_scene(
    lines: list[str],
    *,
    place: str | None = None,
    character: str | None = None,
    user_prompt: str = "",
) -> str:
    speakers: list[str] = []
    settings: list[str] = []
    beats: list[str] = []
    if character:
        speakers.append(character.strip())

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        speaker, action, text = parse_rp_line(line)
        if speaker:
            speakers.append(speaker)
            beats.append(_beat_from_parts(speaker, action, text))
            continue
        prefixed = _SPEAKER_PREFIX.match(text)
        if prefixed:
            name, rest = prefixed.group(1).strip(), _collapse_ws(prefixed.group(2))
            speakers.append(name)
            beats.append(_beat_from_parts(name, None, rest))
            continue
        if text:
            settings.append(clip_text(text, 180))
            beats.append(clip_text(text, 180))

    speakers = _unique(speakers)[:_CAST_LIMIT]
    settings = _unique(settings)
    if len(settings) > _SETTING_SNIPPETS:
        settings = _unique([settings[0], *settings[-(_SETTING_SNIPPETS - 1) :]])

    chunks: list[str] = []
    focus = user_prompt.strip()
    if focus:
        chunks.append(f"Focus: {clip_text(focus, _FOCUS_BUDGET)}")
    now = " ".join(beats[-_NOW_BEATS:])
    if now:
        chunks.append(f"Now: {clip_text_end(now, _NOW_BUDGET)}")
    setting_bits: list[str] = []
    if place:
        setting_bits.append(clip_text(place, MAX_PLACE_CHARS))
    if speakers:
        setting_bits.append("characters " + ", ".join(speakers))
    if setting_bits:
        chunks.append(f"Setting: {clip_text('. '.join(setting_bits), _SETTING_BUDGET)}.")
    if settings:
        chunks.append(f"Environment: {clip_text(' '.join(settings), _ENVIRONMENT_BUDGET)}")
    return " ".join(chunks).strip()


def public_caption(
    *,
    user_prompt: str,
    place: str | None,
    from_scene: bool,
) -> str:
    prompt = user_prompt.strip()
    if prompt and place:
        return clip_text(f"{place} — {prompt}", 200)
    if prompt:
        return clip_text(prompt, 200)
    if place:
        return clip_text(f"{place} — from the scene", 200)
    if from_scene:
        return "from the scene"
    return "generated scene"


def build_prompt(
    *,
    user_prompt: str = "",
    place: str | None = None,
    character: str | None = None,
    scene_lines: list[str] | None = None,
) -> str:
    prompt = user_prompt.strip()
    lines = [line.strip() for line in (scene_lines or []) if line.strip()]
    if not prompt and not lines:
        raise ImagePromptError(
            "Give a prompt, or run this in a channel with roleplay messages."
        )

    summary = summarize_scene(
        lines,
        place=place,
        character=character,
        user_prompt=prompt,
    )
    return clip_text(f"{STYLE_PREFIX} {summary}".strip(), MAX_PROMPT_CHARS)


def filename_for_content_type(content_type: str) -> str:
    lowered = content_type.split(";", 1)[0].strip().casefold()
    if lowered in {"image/png", "png"}:
        return "scene.png"
    if lowered in {"image/webp", "webp"}:
        return "scene.webp"
    return "scene.jpg"


def pollinations_url(
    prompt: str,
    *,
    width: int,
    height: int,
    model: str,
    seed: int,
    base: str = POLLINATIONS_GEN_URL,
    api_key: str | None = None,
) -> str:
    encoded = quote(prompt, safe="")
    query = {
        "width": width,
        "height": height,
        "model": model,
        "nologo": "true",
        "private": "true",
        "enhance": "false",
        "seed": seed,
    }
    if api_key:
        query["key"] = api_key
    return f"{base.rstrip('/')}/{encoded}?{urlencode(query)}"


def _clamp_size(value: int) -> int:
    return max(64, min(int(value), 1280))


def _looks_like_html(data: bytes, content_type: str) -> bool:
    lowered = content_type.split(";", 1)[0].strip().casefold()
    if "html" in lowered or lowered.startswith("text/"):
        return True
    head = data.lstrip()[:32].lower()
    return head.startswith((b"<!doctype", b"<html", b"<head"))


def _is_image_bytes(data: bytes, content_type: str) -> bool:
    if len(data) < 32 or len(data) > MAX_IMAGE_BYTES:
        return False
    if _looks_like_html(data, content_type):
        return False
    if data.startswith((b"\xff\xd8", b"\x89PNG", b"RIFF", b"GIF8")):
        return True
    lowered = content_type.split(";", 1)[0].strip().casefold()
    return lowered.startswith("image/")


async def generate_image(
    prompt: str,
    *,
    seed: int | None = None,
    session: aiohttp.ClientSession | None = None,
) -> GeneratedImage:
    if not prompt.strip():
        raise ImagePromptError(
            "Give a prompt, or run this in a channel with roleplay messages."
        )
    chosen_seed = random.randint(0, 2_147_483_647) if seed is None else seed
    own_session = session is None
    if own_session:
        timeout = aiohttp.ClientTimeout(total=max(15, IMAGE_TIMEOUT_SECONDS))
        session = aiohttp.ClientSession(
            timeout=timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.9,*/*;q=0.1",
            },
        )
    assert session is not None
    try:
        provider = (IMAGE_PROVIDER or "pollinations").strip().casefold()
        if provider in {"local", "a1111", "automatic1111"}:
            return await _generate_local(session, prompt)
        if provider in {"auto", "hybrid"}:
            try:
                return await _generate_local(session, prompt)
            except (ImageGenerationError, aiohttp.ClientError, TimeoutError, OSError) as exc:
                logger.warning("Local image server unavailable (%s); using Pollinations", exc)
                return await _generate_pollinations(session, prompt, seed=chosen_seed)
        if provider not in {"pollinations", "cloud", ""}:
            raise ImageGenerationError(f"Unknown image provider `{IMAGE_PROVIDER}`.")
        return await _generate_pollinations(session, prompt, seed=chosen_seed)
    except TimeoutError as exc:
        raise ImageGenerationError("Image generation timed out. Try again in a minute.") from exc
    except aiohttp.ClientError as exc:
        logger.warning("Image generation request failed: %s", exc)
        raise ImageGenerationError("Image generation is unavailable right now.") from exc
    finally:
        if own_session:
            await session.close()


async def _generate_pollinations(
    session: aiohttp.ClientSession,
    prompt: str,
    *,
    seed: int,
) -> GeneratedImage:
    api_key = (
        os.environ.get("POLLINATIONS_API_KEY")
        or os.environ.get("POLLINATIONS_KEY")
        or None
    )
    bases = (POLLINATIONS_GEN_URL, POLLINATIONS_LEGACY_URL)
    last_status = "no response"
    for attempt in range(3):
        url = pollinations_url(
            prompt,
            width=_clamp_size(IMAGE_WIDTH),
            height=_clamp_size(IMAGE_HEIGHT),
            model=IMAGE_MODEL or "flux",
            seed=seed + attempt,
            base=bases[attempt % len(bases)],
            api_key=api_key,
        )
        headers = {"Accept": "image/jpeg,image/png,image/webp,image/*"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            async with session.get(url, headers=headers) as response:
                body = await response.read()
                content_type = str(response.headers.get("Content-Type") or "")
                last_status = f"HTTP {response.status} ({content_type}, {len(body)} bytes)"
                if response.status < 400 and _is_image_bytes(body, content_type):
                    filename = filename_for_content_type(content_type)
                    return GeneratedImage(
                        data=body,
                        filename=filename,
                        content_type=content_type or "image/jpeg",
                    )
                logger.warning("Pollinations returned %s from %s", last_status, url.split("?", 1)[0])
        except (TimeoutError, aiohttp.ClientError) as exc:
            last_status = str(exc)
            logger.warning("Pollinations request failed (%s): %s", url.split("?", 1)[0], exc)
        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise ImageGenerationError("Image generation is unavailable right now.")


def _decode_a1111_image(raw: str) -> bytes:
    payload = raw.split(",", 1)[-1] if "," in raw else raw
    try:
        return base64.b64decode(payload, validate=False)
    except (ValueError, TypeError) as exc:
        raise ImageGenerationError("The local image server returned a broken image.") from exc


async def _generate_local(session: aiohttp.ClientSession, prompt: str) -> GeneratedImage:
    base = (IMAGE_LOCAL_URL or "http://127.0.0.1:7860").rstrip("/")
    url = f"{base}/sdapi/v1/txt2img"
    payload: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "steps": 20,
        "width": _clamp_size(IMAGE_WIDTH),
        "height": _clamp_size(IMAGE_HEIGHT),
        "cfg_scale": 7,
    }
    async with session.post(url, json=payload) as response:
        body = await response.read()
        if response.status >= 400:
            logger.warning("Local image server HTTP %s", response.status)
            raise ImageGenerationError(
                f"Local image server is not responding at `{base}`."
            )
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ImageGenerationError("The local image server returned invalid JSON.") from exc
        images = data.get("images") if isinstance(data, dict) else None
        if not isinstance(images, list) or not images:
            raise ImageGenerationError("The local image server returned no image.")
        raw = _decode_a1111_image(str(images[0]))
        if not _is_image_bytes(raw, "image/png"):
            raise ImageGenerationError("The local image server returned a broken image.")
        return GeneratedImage(data=raw, filename="scene.png", content_type="image/png")
