import asyncio
import logging
from typing import Any
import aiohttp

from config import (
    GEMINI_API_KEY,
    GEMINI_MAX_OUTPUT_TOKENS,
    GEMINI_MODEL,
    GEMINI_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
FALLBACK_MODELS = (
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
)
# This alias hangs (0-byte read) on the current API.
_UNRELIABLE_MODELS = frozenset({"gemini-flash-latest"})
_RETRYABLE = frozenset({404, 500, 503})
_TIMEOUT_STATUS = 408
_BUSY_PAUSE_SECONDS = 0.8
_REQUEST_READ_SECONDS = 12
_REQUEST_CONNECT_SECONDS = 5
MISSING_KEY = (
    "Gemini n’est pas configuré. Ajoute `GEMINI_API_KEY` dans `.env` "
    "(https://aistudio.google.com/apikey)."
)
_MAX_MESSAGE = 1900
_SAFETY = (
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_ONLY_HIGH"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_ONLY_HIGH"},
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE",
    },
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_ONLY_HIGH"},
)


class GeminiError(Exception):
    pass


class GeminiEmptyReply(GeminiError):
    pass


def require_gemini_key(key: str | None = None) -> str:
    resolved = (key if key is not None else GEMINI_API_KEY) or ""
    resolved = resolved.strip()
    if not resolved:
        raise GeminiError(MISSING_KEY)
    return resolved


def generate_url(*, model: str) -> str:
    chosen = model.strip() or GEMINI_MODEL
    if chosen.startswith("models/"):
        chosen = chosen.split("/", 1)[1]
    return GEMINI_GENERATE_URL.format(model=chosen)


def candidate_models(preferred: str) -> list[str]:
    ordered: list[str] = []
    for name in (preferred, *FALLBACK_MODELS):
        cleaned = name.strip()
        if cleaned.startswith("models/"):
            cleaned = cleaned.split("/", 1)[1]
        if cleaned and cleaned not in ordered and cleaned not in _UNRELIABLE_MODELS:
            ordered.append(cleaned)
    if not ordered:
        ordered.extend(
            name for name in FALLBACK_MODELS if name not in _UNRELIABLE_MODELS
        )
    return ordered


def _error_detail(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"]).strip()
    return ""


def build_generate_body(
    *,
    system: str,
    user: str,
    max_tokens: int = GEMINI_MAX_OUTPUT_TOKENS,
    temperature: float = 0.9,
) -> dict[str, Any]:
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max(64, int(max_tokens)),
            # Gemini 3 default thinking (medium) can consume maxOutputTokens
            # and return an empty candidate.
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
        "safetySettings": list(_SAFETY),
    }


def extract_gemini_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise GeminiError("Gemini a renvoyé une réponse illisible.")
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "erreur inconnue").strip()
        raise GeminiError(f"Gemini : {message}")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        prompt = payload.get("promptFeedback")
        if isinstance(prompt, dict) and prompt.get("blockReason"):
            raise GeminiError("Gemini a bloqué cette consigne (filtres de sécurité).")
        raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
    first = candidates[0]
    if not isinstance(first, dict):
        raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
    reason = str(first.get("finishReason") or "")
    if reason == "SAFETY":
        raise GeminiError("Gemini a bloqué cette consigne (filtres de sécurité).")
    content = first.get("content")
    if not isinstance(content, dict):
        raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
    chunks = [
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("text") and not part.get("thought")
    ]
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
    if not text:
        raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
    return text


def clamp_discord_text(text: str, *, limit: int = _MAX_MESSAGE) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


async def generate_text(
    *,
    system: str,
    user: str,
    key: str | None = None,
    model: str | None = None,
    session: aiohttp.ClientSession | None = None,
) -> str:
    api_key = require_gemini_key(key)
    models = candidate_models((model or GEMINI_MODEL).strip() or GEMINI_MODEL)
    body = build_generate_body(system=system, user=user)
    own_session = session is None
    if session is None:
        timeout = aiohttp.ClientTimeout(
            total=max(5, GEMINI_TIMEOUT_SECONDS),
            sock_connect=_REQUEST_CONNECT_SECONDS,
            sock_read=_REQUEST_READ_SECONDS,
        )
        session = aiohttp.ClientSession(timeout=timeout)
    last_status = 0
    last_model = models[0]
    last_detail = ""
    try:
        for index, chosen_model in enumerate(models):
            url = generate_url(model=chosen_model)
            try:
                async with session.post(
                    url,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": api_key,
                    },
                ) as response:
                    try:
                        payload = await response.json(content_type=None)
                    except aiohttp.ContentTypeError as exc:
                        raise GeminiError(
                            "Gemini a renvoyé une réponse illisible."
                        ) from exc
                    if response.status in _RETRYABLE:
                        last_status = response.status
                        last_model = chosen_model
                        last_detail = _error_detail(payload)
                        logger.info(
                            "Gemini model %s returned %s, trying next",
                            chosen_model,
                            response.status,
                        )
                        if response.status == 503 and index + 1 < len(models):
                            await asyncio.sleep(_BUSY_PAUSE_SECONDS)
                        continue
                    if response.status == 429:
                        raise GeminiError(
                            "Quota Gemini atteint. Réessaie dans une minute."
                        )
                    if response.status == 403:
                        raise GeminiError(
                            "Clé Gemini refusée. Vérifie `GEMINI_API_KEY` dans `.env`."
                        )
                    if response.status >= 400:
                        detail = _error_detail(payload)
                        suffix = f" {detail}" if detail else ""
                        raise GeminiError(
                            f"Gemini est indisponible (HTTP {response.status}).{suffix}"
                        )
                    try:
                        return clamp_discord_text(extract_gemini_text(payload))
                    except GeminiEmptyReply:
                        last_status = response.status
                        last_model = chosen_model
                        last_detail = "empty"
                        usage = (
                            payload.get("usageMetadata")
                            if isinstance(payload.get("usageMetadata"), dict)
                            else {}
                        )
                        first = (
                            payload.get("candidates")[0]
                            if isinstance(payload.get("candidates"), list)
                            and payload.get("candidates")
                            and isinstance(payload.get("candidates")[0], dict)
                            else {}
                        )
                        logger.info(
                            "Gemini model %s empty finish=%s thoughts=%s out=%s, "
                            "trying next",
                            chosen_model,
                            first.get("finishReason"),
                            usage.get("thoughtsTokenCount"),
                            usage.get("candidatesTokenCount"),
                        )
                        continue
            except TimeoutError:
                last_status = _TIMEOUT_STATUS
                last_model = chosen_model
                last_detail = "timeout"
                logger.info("Gemini model %s timed out, trying next", chosen_model)
                continue
            except aiohttp.ClientError as exc:
                logger.warning("Gemini request failed: %s", exc)
                raise GeminiError("Gemini est indisponible pour le moment.") from exc
        if last_status in {500, 503}:
            raise GeminiError(
                "Gemini est saturé en ce moment. Réessaie dans une minute."
            )
        if last_status == _TIMEOUT_STATUS:
            raise GeminiError("Gemini a mis trop longtemps. Réessaie.")
        if last_detail == "empty":
            raise GeminiEmptyReply("Gemini n’a rien renvoyé.")
        extra = f" {last_detail}" if last_detail else ""
        raise GeminiError(
            f"Modèle `{last_model}` introuvable.{extra} "
            "Essaie `GEMINI_MODEL=gemini-3.5-flash`."
        )
    finally:
        if own_session:
            await session.close()
