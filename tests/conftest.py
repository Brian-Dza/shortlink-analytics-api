"""Pytest fixtures for isolated ASGI, async database, and Redis testing."""

import math
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateColumn
from sqlalchemy.sql.compiler import DDLCompiler

from app.core.config import Settings
from app.core.database import Base, create_session_factory
from app.main import create_app


class InMemoryAsyncRedis:
    """Lightweight async Redis double supporting cache and atomic fixed-window Lua eval."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _evict_if_expired(self, key: str) -> None:
        entry = self._store.get(key)
        if entry is not None and entry[1] is not None and time.monotonic() >= entry[1]:
            del self._store[key]

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        self._evict_if_expired(key)
        entry = self._store.get(key)
        return entry[0] if entry is not None else None

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        expires_at = (time.monotonic() + ex) if ex is not None else None
        self._store[key] = (value, expires_at)
        return True

    async def delete(self, key: str) -> int:
        return 1 if self._store.pop(key, None) is not None else 0

    async def ttl(self, key: str) -> int:
        self._evict_if_expired(key)
        entry = self._store.get(key)
        if entry is None:
            return -2
        if entry[1] is None:
            return -1
        return max(1, math.ceil(entry[1] - time.monotonic()))

    async def eval(
        self,
        _script: str,
        numkeys: int,
        key: str,
        window_seconds: int,
    ) -> list[int]:
        assert numkeys == 1
        self._evict_if_expired(key)
        now = time.monotonic()
        entry = self._store.get(key)
        if entry is None:
            current = 1
            expires_at = now + int(window_seconds)
        else:
            current = int(entry[0]) + 1
            expires_at = entry[1] if entry[1] is not None else now + int(window_seconds)
        self._store[key] = (str(current), expires_at)
        ttl_remaining = max(1, math.ceil(expires_at - now))
        return [current, ttl_remaining]

    async def aclose(self) -> None:
        self._store.clear()


@compiles(CreateColumn, "sqlite")
def _strip_pg_uuid_default_for_sqlite(
    element: CreateColumn,
    compiler: DDLCompiler,
    **kw: object,
) -> str:
    """Strip PostgreSQL-only gen_random_uuid() defaults when running on SQLite."""
    ddl = compiler.visit_create_column(element, **kw)
    return ddl.replace(" DEFAULT gen_random_uuid()", "")


@pytest.fixture
def test_settings() -> Settings:
    """Provide deterministic test configuration without reading a .env file."""
    return Settings(
        _env_file=None,
        app_name="shortlink-analytics-api-test",
        app_env="test",
        debug=False,
        base_url="http://testserver",
        log_level="WARNING",
        database_url="postgresql+asyncpg://test:test@localhost:5432/test_db",
        redis_url="redis://localhost:6379/15",
        jwt_secret_key=SecretStr("test-jwt-secret-key-with-at-least-32-chars"),
        ip_hash_salt=SecretStr("test-ip-hash-salt-16"),
    )


@pytest.fixture
async def db_engine() -> AsyncIterator[AsyncEngine]:
    """Create an isolated async database engine (PostgreSQL if configured, else SQLite)."""
    import app.models  # noqa: F401

    test_db_url = os.getenv("TEST_DATABASE_URL")
    if test_db_url:
        engine = create_async_engine(test_db_url, pool_pre_ping=True)
    else:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis | InMemoryAsyncRedis]:
    """Provide an isolated Redis client (real Redis if TEST_REDIS_URL is set, else in-memory)."""
    test_redis_url = os.getenv("TEST_REDIS_URL")
    if test_redis_url:
        client: Redis | InMemoryAsyncRedis = Redis.from_url(
            test_redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await client.flushdb()
        try:
            yield client
        finally:
            await client.flushdb()
            await client.aclose()
    else:
        in_memory = InMemoryAsyncRedis()
        try:
            yield in_memory
        finally:
            await in_memory.aclose()


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Create a fresh FastAPI application instance for each test."""
    return create_app(settings=test_settings)


@pytest.fixture
async def client(
    app: FastAPI,
    db_engine: AsyncEngine,
    redis_client: Redis | InMemoryAsyncRedis,
) -> AsyncIterator[AsyncClient]:
    """Provide an async HTTP client wired to isolated test DB and Redis instances."""
    async with app.router.lifespan_context(app):
        default_engine = app.state.db_engine
        default_redis = app.state.redis
        app.state.db_engine = db_engine
        app.state.session_factory = create_session_factory(db_engine)
        app.state.redis = redis_client
        await default_engine.dispose()
        await default_redis.aclose()

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as ac:
            yield ac


@pytest.fixture
def auth_user_factory(
    client: AsyncClient,
) -> Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]]:
    """Register and authenticate a test user, returning (headers, user_payload)."""

    async def _create_user(
        email: str = "owner@example.com",
        password: str = "StrongPass123!",
    ) -> tuple[dict[str, str], dict[str, object]]:
        register_resp = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password},
        )
        assert register_resp.status_code == 201
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}, register_resp.json()

    return _create_user
