"""Tests for Cache-Aside Redis caching, HTTP 307 redirects, invalidation, and fallback."""

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import update

from app.core.redis import cache_set_link, link_cache_key
from app.models.link import Link
from app.repositories.link_repository import LinkRepository
from app.schemas.link import LinkCachePayload
from tests.conftest import InMemoryAsyncRedis


class _BrokenRedis:
    """Stub Redis client that raises ConnectionError on every operation."""

    async def ping(self) -> bool:
        raise RedisConnectionError("Redis unavailable")

    async def get(self, _key: str) -> str | None:
        raise RedisConnectionError("Redis unavailable")

    async def set(self, _key: str, _value: str, ex: int | None = None) -> bool:
        raise RedisConnectionError("Redis unavailable")

    async def delete(self, _key: str) -> int:
        raise RedisConnectionError("Redis unavailable")

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        _key: str,
        _window: int,
    ) -> list[int]:
        raise RedisConnectionError("Redis unavailable")

    async def aclose(self) -> None:
        return None


async def test_redirect_307_cache_miss_then_cache_hit_without_db_query(
    client: AsyncClient,
    redis_client: InMemoryAsyncRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First redirect warms Redis cache (miss); second hits Redis without DB query."""
    create_resp = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/cache-test", "custom_alias": "cache1"},
    )
    assert create_resp.status_code == 201
    link_id = create_resp.json()["id"]

    cache_key = link_cache_key("cache1")
    assert await redis_client.get(cache_key) is None

    first = await client.get("/cache1", follow_redirects=False)
    assert first.status_code == 307
    assert first.headers["Location"] == "https://example.com/cache-test"
    assert first.headers["Cache-Control"] == "no-store"

    cached_raw = await redis_client.get(cache_key)
    assert cached_raw is not None
    cached_json = json.loads(cached_raw)
    assert cached_json["link_id"] == link_id
    assert cached_json["original_url"] == "https://example.com/cache-test"
    ttl = await redis_client.ttl(cache_key)
    assert 0 < ttl <= 86400

    async def fail_if_db_called(self: object, short_code: str) -> None:
        raise AssertionError(f"PostgreSQL should not be queried on cache hit: {short_code}")

    monkeypatch.setattr(LinkRepository, "get_by_short_code", fail_if_db_called)

    second = await client.get("/cache1", follow_redirects=False)
    assert second.status_code == 307
    assert second.headers["Location"] == "https://example.com/cache-test"


async def test_redirect_missing_or_inactive_returns_404(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Unknown or deactivated short codes return 404 LINK_NOT_FOUND."""
    missing = await client.get("/missing99", follow_redirects=False)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LINK_NOT_FOUND"

    headers, _ = await auth_user_factory("inactive@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/off", "custom_alias": "offlink"},
    )
    assert created.status_code == 201

    deactivated = await client.patch(
        "/api/v1/links/offlink",
        headers=headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    redirect_resp = await client.get("/offlink", follow_redirects=False)
    assert redirect_resp.status_code == 404
    assert redirect_resp.json()["error"]["code"] == "LINK_NOT_FOUND"


async def test_redirect_expired_link_returns_410_and_evicts_cache(
    app: FastAPI,
    client: AsyncClient,
    redis_client: InMemoryAsyncRedis,
) -> None:
    """Expired links return 410 LINK_EXPIRED both from cache (evicting it) and DB."""
    stale_payload = LinkCachePayload(
        link_id=uuid.uuid4(),
        original_url="https://example.com/stale",
        is_active=True,
        expires_at=datetime.now(UTC) - timedelta(seconds=30),
    )
    await cache_set_link(redis_client, "cachedexp", stale_payload, ttl_seconds=60)  # type: ignore[arg-type]

    cached_resp = await client.get("/cachedexp", follow_redirects=False)
    assert cached_resp.status_code == 410
    assert cached_resp.json()["error"]["code"] == "LINK_EXPIRED"
    assert await redis_client.get(link_cache_key("cachedexp")) is None

    created = await client.post(
        "/api/v1/links",
        json={
            "original_url": "https://example.com/db-exp",
            "custom_alias": "dbexp1",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    )
    assert created.status_code == 201

    async with app.state.session_factory() as session:
        await session.execute(
            update(Link)
            .where(Link.short_code == "dbexp1")
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=5))
        )
        await session.commit()

    db_resp = await client.get("/dbexp1", follow_redirects=False)
    assert db_resp.status_code == 410
    assert db_resp.json()["error"]["code"] == "LINK_EXPIRED"


async def test_patch_invalidates_redis_cache_immediately(
    client: AsyncClient,
    redis_client: InMemoryAsyncRedis,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Updating a link deletes its Redis entry so redirects never serve stale URLs."""
    headers, _ = await auth_user_factory("patchcache@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/v1", "custom_alias": "patch1"},
    )
    assert created.status_code == 201

    warm = await client.get("/patch1", follow_redirects=False)
    assert warm.status_code == 307
    assert await redis_client.get(link_cache_key("patch1")) is not None

    patched = await client.patch(
        "/api/v1/links/patch1",
        headers=headers,
        json={"original_url": "https://example.com/v2"},
    )
    assert patched.status_code == 200
    assert await redis_client.get(link_cache_key("patch1")) is None

    refreshed = await client.get("/patch1", follow_redirects=False)
    assert refreshed.status_code == 307
    assert refreshed.headers["Location"] == "https://example.com/v2"
    cached_raw = await redis_client.get(link_cache_key("patch1"))
    assert cached_raw is not None
    assert json.loads(cached_raw)["original_url"] == "https://example.com/v2"


async def test_delete_invalidates_redis_cache_immediately(
    client: AsyncClient,
    redis_client: InMemoryAsyncRedis,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Deleting a link removes its cached Redis key and stops future redirects."""
    headers, _ = await auth_user_factory("delcache@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/bye", "custom_alias": "del123"},
    )
    assert created.status_code == 201

    warm = await client.get("/del123", follow_redirects=False)
    assert warm.status_code == 307
    assert await redis_client.get(link_cache_key("del123")) is not None

    deleted = await client.delete("/api/v1/links/del123", headers=headers)
    assert deleted.status_code == 204
    assert await redis_client.get(link_cache_key("del123")) is None

    after = await client.get("/del123", follow_redirects=False)
    assert after.status_code == 404
    assert after.json()["error"]["code"] == "LINK_NOT_FOUND"


async def test_graceful_degradation_when_redis_raises_connection_error(
    app: FastAPI,
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """When Redis is down, redirect falls back to PostgreSQL and CRUD still succeeds."""
    headers, _ = await auth_user_factory("resilient@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/resilient", "custom_alias": "resil1"},
    )
    assert created.status_code == 201

    app.state.redis = _BrokenRedis()

    redirect_resp = await client.get("/resil1", follow_redirects=False)
    assert redirect_resp.status_code == 307
    assert redirect_resp.headers["Location"] == "https://example.com/resilient"

    patched = await client.patch(
        "/api/v1/links/resil1",
        headers=headers,
        json={"original_url": "https://example.com/resilient-v2"},
    )
    assert patched.status_code == 200

    redirect_v2 = await client.get("/resil1", follow_redirects=False)
    assert redirect_v2.status_code == 307
    assert redirect_v2.headers["Location"] == "https://example.com/resilient-v2"

    deleted = await client.delete("/api/v1/links/resil1", headers=headers)
    assert deleted.status_code == 204
