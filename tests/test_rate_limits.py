import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import discord
from discord.errors import RateLimited

from bot.rate_limits import (
    discord_retry_after,
    header_value,
    is_cloudflare_ban,
    is_permanent_http_error,
    is_rate_limited,
    parse_retry_after,
    rate_limit_scope,
    retry_after_from_headers,
    retry_on_rate_limit,
    should_retry_rate_limit,
    sleep_discord_retry,
)


def _http_error(
    status: int,
    reason: str = "error",
    *,
    headers: dict[str, str] | None = None,
) -> discord.HTTPException:
    response = MagicMock()
    response.status = status
    response.reason = reason
    response.headers = headers or {}
    return discord.HTTPException(response, {"message": reason})


class TestHeaderParsing(unittest.TestCase):
    def test_reads_known_header_names(self) -> None:
        headers = {"Retry-After": "1.5", "X-RateLimit-Scope": "user"}
        self.assertEqual(header_value(headers, "Retry-After"), "1.5")
        self.assertEqual(header_value(headers, "X-RateLimit-Scope"), "user")
        self.assertIsNone(header_value(headers, "Via"))

    def test_ignores_magicmock_header_values(self) -> None:
        self.assertIsNone(header_value(MagicMock(), "Retry-After"))

    def test_parse_retry_after(self) -> None:
        self.assertEqual(parse_retry_after("2.25"), 2.25)
        self.assertEqual(parse_retry_after(1), 1.0)
        self.assertIsNone(parse_retry_after("nope"))
        self.assertIsNone(parse_retry_after(-1))

    def test_retry_after_from_headers_prefers_retry_after(self) -> None:
        self.assertEqual(
            retry_after_from_headers(
                {"Retry-After": "3", "X-RateLimit-Reset-After": "9"}
            ),
            3.0,
        )
        self.assertEqual(
            retry_after_from_headers({"X-RateLimit-Reset-After": "4.5"}),
            4.5,
        )
        self.assertEqual(
            retry_after_from_headers({}, fallback=2.0),
            2.0,
        )


class TestDiscordExceptionHelpers(unittest.TestCase):
    def test_rate_limited_uses_retry_after(self) -> None:
        exc = RateLimited(2.5)
        self.assertTrue(is_rate_limited(exc))
        self.assertEqual(discord_retry_after(exc), 2.5)
        self.assertTrue(should_retry_rate_limit(exc))
        self.assertFalse(is_cloudflare_ban(exc))

    def test_http_429_without_via_is_cloudflare_ban(self) -> None:
        exc = _http_error(429, "Too Many Requests")
        self.assertTrue(is_rate_limited(exc))
        self.assertTrue(is_cloudflare_ban(exc))
        self.assertFalse(should_retry_rate_limit(exc))
        self.assertIsNone(discord_retry_after(exc))

    def test_discord_api_429_without_via_is_retryable(self) -> None:
        exc = _http_error(429, "You are being rate limited.")
        self.assertTrue(is_rate_limited(exc))
        self.assertFalse(is_cloudflare_ban(exc))
        self.assertTrue(should_retry_rate_limit(exc))

    def test_http_429_with_retry_after_without_via_is_retryable(self) -> None:
        exc = _http_error(
            429,
            "Too Many Requests",
            headers={"Retry-After": "2.5"},
        )
        self.assertFalse(is_cloudflare_ban(exc))
        self.assertTrue(should_retry_rate_limit(exc))
        self.assertEqual(discord_retry_after(exc), 2.5)

    def test_http_429_with_via_and_retry_after_is_retryable(self) -> None:
        exc = _http_error(
            429,
            "Too Many Requests",
            headers={
                "Via": "1.1 google",
                "Retry-After": "1.25",
                "X-RateLimit-Scope": "shared",
            },
        )
        self.assertTrue(should_retry_rate_limit(exc))
        self.assertFalse(is_cloudflare_ban(exc))
        self.assertEqual(discord_retry_after(exc), 1.25)
        self.assertEqual(rate_limit_scope(exc), "shared")

    def test_does_not_retry_401_403_404(self) -> None:
        for status in (401, 403, 404):
            exc = _http_error(status, "no")
            self.assertTrue(is_permanent_http_error(exc))
            self.assertFalse(should_retry_rate_limit(exc))


class TestRetryOnRateLimit(unittest.IsolatedAsyncioTestCase):
    async def test_retries_after_waiting_retry_after(self) -> None:
        limited = _http_error(
            429,
            "Too Many Requests",
            headers={"Via": "1.1 google", "Retry-After": "8"},
        )
        operation = AsyncMock(side_effect=[limited, "ok"])
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await retry_on_rate_limit(operation)
        self.assertEqual(result, "ok")
        sleep.assert_awaited_once_with(8.0)
        self.assertEqual(operation.await_count, 2)

    async def test_retries_discord_api_429_without_headers(self) -> None:
        limited = _http_error(429, "You are being rate limited.")
        operation = AsyncMock(side_effect=[limited, "ok"])
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock) as sleep:
            result = await retry_on_rate_limit(operation)
        self.assertEqual(result, "ok")
        sleep.assert_awaited_once_with(1.0)
        self.assertEqual(operation.await_count, 2)

    async def test_does_not_retry_cloudflare_ban(self) -> None:
        limited = _http_error(429, "Too Many Requests")
        operation = AsyncMock(side_effect=limited)
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaises(discord.HTTPException):
                await retry_on_rate_limit(operation)
        sleep.assert_not_awaited()
        operation.assert_awaited_once()

    async def test_does_not_retry_forbidden(self) -> None:
        response = MagicMock()
        response.status = 403
        response.reason = "Forbidden"
        response.headers = {}
        operation = AsyncMock(side_effect=discord.Forbidden(response, "no"))
        with self.assertRaises(discord.Forbidden):
            await retry_on_rate_limit(operation)
        operation.assert_awaited_once()

    async def test_caps_sleep(self) -> None:
        exc = RateLimited(120)
        with patch("bot.rate_limits.asyncio.sleep", new_callable=AsyncMock) as sleep:
            waited = await sleep_discord_retry(exc, cap=5)
        self.assertEqual(waited, 5)
        sleep.assert_awaited_once_with(5)
