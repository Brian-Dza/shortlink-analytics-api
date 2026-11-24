"""Async Redis client factory, cleanup, health check, and tolerant cache helpers."""

import asyncio
import logging

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.schemas.link import LinkCachePayload

logger = logging.getLogger(__name__)


def create_redis_client(settings: Settings) -> Redis:
    """Create a pooled async Redis client configured with short socket timeouts."""
    return Redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2.0,
        socket_timeout=2.0,
    )


async def close_redis_client(client: Redis) -> None:
    """Close the Redis connection pool gracefully."""
    await client.aclose()


async def check_redis_connection(
    client: Redis | None,
    timeout_seconds: float = 2.0,
) -> bool:
    """Verify live Redis connectivity using PING within a bounded timeout."""
    if client is None:
        return False

    async def _ping() -> bool:
        return bool(await client.ping())

    try:
        return await asyncio.wait_for(_ping(), timeout=timeout_seconds)
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Redis health check failed: %s", type(exc).__name__)
        return False


def link_cache_key(short_code: str) -> str:
    """Return the canonical Redis key for a cached short link."""
    return f"link:{short_code}"


async def cache_get_link(client: Redis | None, short_code: str) -> LinkCachePayload | None:
    """Read a cached link payload from Redis, degrading cleanly to None on errors."""
    if client is None:
        return None

    key = link_cache_key(short_code)
    try:
        raw = await client.get(key)
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Redis cache GET failed for %s: %s", key, type(exc).__name__)
        return None

    if raw is None:
        return None

    try:
        return LinkCachePayload.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        logger.warning("Corrupt Redis cache payload for %s: %s", key, type(exc).__name__)
        return None


async def cache_set_link(
    client: Redis | None,
    short_code: str,
    payload: LinkCachePayload,
    ttl_seconds: int,
) -> None:
    """Store a serialized link payload in Redis with TTL, ignoring Redis failures."""
    if client is None or ttl_seconds <= 0:
        return

    key = link_cache_key(short_code)
    try:
        await client.set(key, payload.model_dump_json(), ex=ttl_seconds)
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Redis cache SET failed for %s: %s", key, type(exc).__name__)


async def cache_delete_link(client: Redis | None, short_code: str) -> None:
    """Invalidate a cached short link entry in Redis, ignoring Redis failures."""
    if client is None:
        return

    key = link_cache_key(short_code)
    try:
        await client.delete(key)
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning("Redis cache DELETE failed for %s: %s", key, type(exc).__name__)
