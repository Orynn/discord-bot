"""Follow Discord rate-limit headers instead of hard-coded quotas.

See https://docs.discord.com/developers/topics/rate-limits
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from discord.errors import HTTPException, RateLimited

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Bound a single wait so a long Retry-After cannot stall a user command.
MAX_RETRY_WAIT = 60.0
DEFAULT_ATTEMPTS = 2
DEFAULT_429_WAIT = 1.0


def header_value(headers: object | None, *names: str) -> str | None:
    if headers is None:
        return None
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    for name in names:
        value = getter(name)
        if isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text:
                return text
    return None


def parse_retry_after(value: object) -> float | None:
    if value is None:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        return None
    if delay < 0:
        return None
    return delay


def retry_after_from_headers(
    headers: object | None, *, fallback: float | None = None
) -> float | None:
    delay = parse_retry_after(
        header_value(headers, "Retry-After", "X-RateLimit-Reset-After")
    )
    if delay is not None:
        return delay
    return fallback


def discord_retry_after(exc: BaseException) -> float | None:
    if isinstance(exc, RateLimited):
        return parse_retry_after(exc.retry_after)
    if not isinstance(exc, HTTPException):
        return None
    return retry_after_from_headers(getattr(exc.response, "headers", None))


def rate_limit_scope(exc: BaseException) -> str | None:
    if not isinstance(exc, HTTPException):
        return None
    value = header_value(getattr(exc.response, "headers", None), "X-RateLimit-Scope")
    if value in {"user", "global", "shared"}:
        return value
    return None


def is_rate_limited(exc: BaseException) -> bool:
    if isinstance(exc, RateLimited):
        return True
    return isinstance(exc, HTTPException) and exc.status == 429


def is_permanent_http_error(exc: BaseException) -> bool:
    """401 / 403 / 404 must not be retried (invalid-request budget)."""
    if not isinstance(exc, HTTPException):
        return False
    return exc.status in {401, 403, 404}


def _discord_rate_limit_text(exc: BaseException) -> str:
    return str(getattr(exc, "text", None) or exc).casefold()


def is_cloudflare_ban(exc: BaseException) -> bool:
    """HTML / empty 429 without Retry-After is a Cloudflare ban; do not hammer it."""
    if not is_rate_limited(exc) or isinstance(exc, RateLimited):
        return False
    if discord_retry_after(exc) is not None:
        return False
    if "rate limited" in _discord_rate_limit_text(exc):
        return False
    if not isinstance(exc, HTTPException):
        return False
    return header_value(getattr(exc.response, "headers", None), "Via") is None


def should_retry_rate_limit(exc: BaseException) -> bool:
    if is_permanent_http_error(exc):
        return False
    if not is_rate_limited(exc):
        return False
    return not is_cloudflare_ban(exc)


async def sleep_discord_retry(
    exc: BaseException,
    *,
    cap: float = MAX_RETRY_WAIT,
    fallback: float = DEFAULT_429_WAIT,
) -> float | None:
    delay = discord_retry_after(exc)
    if delay is None:
        if not is_rate_limited(exc):
            return None
        delay = fallback
    wait = min(delay, max(cap, 0.0))
    logger.info(
        "Discord rate limit (scope=%s), waiting %.2fs",
        rate_limit_scope(exc) or "unknown",
        wait,
    )
    await asyncio.sleep(wait)
    return wait


async def retry_on_rate_limit(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    cap: float = MAX_RETRY_WAIT,
) -> T:
    last: BaseException | None = None
    for attempt in range(max(attempts, 1)):
        try:
            return await operation()
        except RateLimited as exc:
            last = exc
            if attempt + 1 >= attempts or not should_retry_rate_limit(exc):
                raise
            await sleep_discord_retry(exc, cap=cap)
        except HTTPException as exc:
            last = exc
            if attempt + 1 >= attempts or not should_retry_rate_limit(exc):
                raise
            await sleep_discord_retry(exc, cap=cap)
    assert last is not None
    raise last
