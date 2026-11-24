"""Tests for Redis distributed rate limiting on POST /api/v1/links."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import Settings


class _BrokenRateLimitRedis:
    """Stub Redis client simulating Redis outage during rate limiting."""

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        _key: str,
        _window: int,
    ) -> list[int]:
        raise RedisConnectionError("Redis connection refused")

    async def aclose(self) -> None:
        return None


async def test_anonymous_rate_limit_blocks_11th_request_with_429_and_retry_after(
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    """Anonymous callers are capped at 10 req/min per IP and receive 429 + Retry-After."""
    limit = test_settings.rate_limit_anon_max_requests
    for idx in range(limit):
        resp = await client.post(
            "/api/v1/links",
            headers={"X-Forwarded-For": "203.0.113.10"},
            json={"original_url": f"https://example.com/anon/{idx}"},
        )
        assert resp.status_code == 201

    blocked = await client.post(
        "/api/v1/links",
        headers={"X-Forwarded-For": "203.0.113.10"},
        json={"original_url": "https://example.com/anon/blocked"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    retry_after = int(blocked.headers["Retry-After"])
    assert 1 <= retry_after <= test_settings.rate_limit_window_seconds

    other_ip = await client.post(
        "/api/v1/links",
        headers={"X-Forwarded-For": "203.0.113.11"},
        json={"original_url": "https://example.com/anon/other"},
    )
    assert other_ip.status_code == 201


async def test_authenticated_rate_limit_allows_30_and_blocks_31st(
    client: AsyncClient,
    test_settings: Settings,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Authenticated callers are capped at 30 req/min per user ID."""
    headers, _ = await auth_user_factory("ratelimit@example.com", "StrongPass123!")
    request_headers = {**headers, "X-Forwarded-For": "203.0.113.20"}

    limit = test_settings.rate_limit_auth_max_requests
    for idx in range(limit):
        resp = await client.post(
            "/api/v1/links",
            headers=request_headers,
            json={"original_url": f"https://example.com/auth/{idx}"},
        )
        assert resp.status_code == 201

    blocked = await client.post(
        "/api/v1/links",
        headers=request_headers,
        json={"original_url": "https://example.com/auth/blocked"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    retry_after = int(blocked.headers["Retry-After"])
    assert 1 <= retry_after <= test_settings.rate_limit_window_seconds


async def test_rate_limiter_fails_open_when_redis_is_down(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    """Rate limiter degrades fail-open instead of returning 500 when Redis fails."""
    app.state.redis = _BrokenRateLimitRedis()

    response = await client.post(
        "/api/v1/links",
        headers={"X-Forwarded-For": "203.0.113.99"},
        json={"original_url": "https://example.com/fail-open"},
    )

    assert response.status_code == 201
