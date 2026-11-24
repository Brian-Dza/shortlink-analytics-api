"""Distributed atomic rate limiting backed by Redis Lua scripting."""

import logging

from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.exceptions import RateLimitExceededException

logger = logging.getLogger(__name__)

# Atomic fixed-window counter: increments key, sets expiration on first hit,
# recovers missing TTL if needed, and returns {current_count, ttl_seconds}.
_FIXED_WINDOW_LUA = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
if ttl < 0 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {current, ttl}
"""


def extract_client_ip(request: Request) -> str:
    """Extract client IP honoring X-Forwarded-For when present."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        first_ip = forwarded_for.split(",", maxsplit=1)[0].strip()
        if first_ip:
            return first_ip
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


async def check_rate_limit(
    *,
    redis_client: Redis | None,
    scope: str,
    identifier: str,
    max_requests: int,
    window_seconds: int,
) -> None:
    """Enforce a distributed Redis fixed-window rate limit with fail-open degradation."""
    key = f"ratelimit:{scope}:{identifier}"
    if redis_client is None:
        logger.warning("Redis client unavailable; rate limiter failing open for key %s", key)
        return

    try:
        result = await redis_client.eval(_FIXED_WINDOW_LUA, 1, key, window_seconds)  # type: ignore[misc]
    except (RedisError, OSError, TimeoutError) as exc:
        logger.warning(
            "Redis rate limiter unavailable (fail-open) for key %s: %s",
            key,
            type(exc).__name__,
        )
        return

    current_count = int(result[0])
    ttl_seconds = int(result[1])
    if current_count > max_requests:
        raise RateLimitExceededException(retry_after=max(1, ttl_seconds))
