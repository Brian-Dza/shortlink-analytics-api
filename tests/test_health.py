"""Tests for GET /health and global standardized JSON error handling."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints import health as health_endpoint
from app.core.exceptions import RateLimitExceededException


async def test_health_returns_200_when_services_are_up(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return 200 OK when both PostgreSQL and Redis pings succeed."""

    async def ok_db(_: object) -> bool:
        return True

    async def ok_redis(_: object) -> bool:
        return True

    monkeypatch.setattr(health_endpoint, "check_db_connection", ok_db)
    monkeypatch.setattr(health_endpoint, "check_redis_connection", ok_redis)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["services"] == {"postgres": "up", "redis": "up"}
    assert body["timestamp"].endswith("Z")


async def test_health_returns_503_when_postgres_is_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return 503 Degraded when PostgreSQL is unreachable."""

    async def down_db(_: object) -> bool:
        return False

    async def ok_redis(_: object) -> bool:
        return True

    monkeypatch.setattr(health_endpoint, "check_db_connection", down_db)
    monkeypatch.setattr(health_endpoint, "check_redis_connection", ok_redis)

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"] == {"postgres": "down", "redis": "up"}


async def test_health_returns_503_when_redis_is_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return 503 Degraded when Redis is unreachable."""

    async def ok_db(_: object) -> bool:
        return True

    async def down_redis(_: object) -> bool:
        return False

    monkeypatch.setattr(health_endpoint, "check_db_connection", ok_db)
    monkeypatch.setattr(health_endpoint, "check_redis_connection", down_redis)

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"] == {"postgres": "up", "redis": "down"}


async def test_health_returns_503_when_all_services_are_down(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return 503 Degraded when both PostgreSQL and Redis are unreachable."""

    async def down_db(_: object) -> bool:
        return False

    async def down_redis(_: object) -> bool:
        return False

    monkeypatch.setattr(health_endpoint, "check_db_connection", down_db)
    monkeypatch.setattr(health_endpoint, "check_redis_connection", down_redis)

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"] == {"postgres": "down", "redis": "down"}


async def test_unknown_route_returns_standardized_404_json(client: AsyncClient) -> None:
    """Return standardized JSON error envelope on unknown API routes."""
    response = await client.get("/api/v1/non-existent-path")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert body["error"]["message"]
    assert body["error"]["timestamp"].endswith("Z")


async def test_validation_error_returns_standardized_422_json(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    """Return standardized JSON with field details when request validation fails."""

    @app.get("/_test/validate")
    async def validate_route(limit: int) -> dict[str, int]:
        return {"limit": limit}

    response = await client.get("/_test/validate", params={"limit": "not-an-int"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed."
    assert body["error"]["timestamp"].endswith("Z")
    assert body["error"]["details"]
    assert body["error"]["details"][0]["field"] == "query.limit"


async def test_app_exception_returns_standardized_error_and_headers(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    """Propagate AppException code, status, and custom headers such as Retry-After."""

    @app.get("/_test/rate-limit")
    async def rate_limit_route() -> None:
        raise RateLimitExceededException(retry_after=42)

    response = await client.get("/_test/rate-limit")

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["error"]["message"] == "Rate limit exceeded. Please retry later."
    assert body["error"]["timestamp"].endswith("Z")


async def test_unhandled_exception_returns_500_without_leaking_trace(app: FastAPI) -> None:
    """Ensure unhandled exceptions return a sanitized 500 JSON payload."""

    @app.get("/_test/crash")
    async def crash_route() -> None:
        raise RuntimeError("secret-internal-detail")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as raw_client,
    ):
        response = await raw_client.get("/_test/crash")

    assert response.status_code == 500
    assert "secret-internal-detail" not in response.text
    assert "Traceback" not in response.text
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert body["error"]["message"] == "An unexpected internal error occurred."
    assert body["error"]["timestamp"].endswith("Z")
