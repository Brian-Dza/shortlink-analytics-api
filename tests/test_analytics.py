"""Tests for async BackgroundTasks click telemetry, IP hashing, and /stats aggregations."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import asyncpg as pg_asyncpg

from app.core.config import Settings
from app.core.redis import link_cache_key
from app.core.security import hash_ip_address
from app.models.click_event import ClickEvent
from app.repositories.click_repository import ClickRepository
from tests.conftest import InMemoryAsyncRedis

CHROME_MAC_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
SAFARI_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1"
)
FIREFOX_LINUX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:129.0) Gecko/20100101 Firefox/129.0"


async def test_redirect_records_click_on_miss_and_cache_hit_with_hashed_ip(
    app: FastAPI,
    client: AsyncClient,
    redis_client: InMemoryAsyncRedis,
    test_settings: Settings,
) -> None:
    """Click telemetry is persisted on both Cache Miss and Cache Hit with hashed IP."""
    created = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/tracked", "custom_alias": "track1"},
    )
    assert created.status_code == 201
    link_id = uuid.UUID(created.json()["id"])

    miss_resp = await client.get(
        "/track1",
        headers={
            "User-Agent": CHROME_MAC_UA,
            "Referer": "https://github.com/org/repo",
            "X-Forwarded-For": "198.51.100.42",
        },
        follow_redirects=False,
    )
    assert miss_resp.status_code == 307
    assert await redis_client.get(link_cache_key("track1")) is not None

    hit_resp = await client.get(
        "/track1",
        headers={
            "User-Agent": SAFARI_IOS_UA,
            "X-Forwarded-For": "203.0.113.55",
        },
        follow_redirects=False,
    )
    assert hit_resp.status_code == 307

    async with app.state.session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(ClickEvent)
                    .where(ClickEvent.link_id == link_id)
                    .order_by(ClickEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    salt = test_settings.ip_hash_salt.get_secret_value()

    first, second = rows[0], rows[1]
    assert first.browser == "Chrome"
    assert first.os == "Mac OS X"
    assert first.device_type == "Desktop"
    assert first.referer == "github.com"
    assert len(first.ip_hash or "") == 64
    assert first.ip_hash == hash_ip_address("198.51.100.42", salt)
    assert "198.51.100.42" not in (first.ip_hash or "")

    assert second.browser == "Mobile Safari"
    assert second.os == "iOS"
    assert second.device_type == "Mobile"
    assert second.referer is None
    assert second.ip_hash == hash_ip_address("203.0.113.55", salt)
    assert "203.0.113.55" not in (second.ip_hash or "")


async def test_stats_endpoint_aggregates_metrics_and_filters_by_days(
    app: FastAPI,
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """GET /stats aggregates total clicks, daily series, and top breakdowns."""
    headers, _ = await auth_user_factory("stats@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/analytics", "custom_alias": "stats1"},
    )
    assert created.status_code == 201
    link_id = uuid.UUID(created.json()["id"])

    for _ in range(2):
        res = await client.get(
            "/stats1",
            headers={"User-Agent": CHROME_MAC_UA, "Referer": "https://github.com/trending"},
            follow_redirects=False,
        )
        assert res.status_code == 307

    res_ff = await client.get(
        "/stats1",
        headers={"User-Agent": FIREFOX_LINUX_UA},
        follow_redirects=False,
    )
    assert res_ff.status_code == 307

    # Insert one historical click 15 days ago (outside 7d window, inside 30d window).
    async with app.state.session_factory() as session:
        session.add(
            ClickEvent(
                link_id=link_id,
                clicked_at=datetime.now(UTC) - timedelta(days=15),
                browser="Safari",
                os="iOS",
                device_type="Mobile",
                referer="news.ycombinator.com",
                ip_hash="a" * 64,
            )
        )
        await session.commit()

    stats_7 = await client.get("/api/v1/links/stats1/stats?days=7", headers=headers)
    assert stats_7.status_code == 200
    body_7 = stats_7.json()
    assert body_7["short_code"] == "stats1"
    assert body_7["original_url"] == "https://example.com/analytics"
    assert body_7["total_clicks"] == 4
    assert body_7["period_days"] == 7
    assert sum(day["clicks"] for day in body_7["clicks_by_day"]) == 3
    assert body_7["top_browsers"][0] == {"label": "Chrome", "clicks": 2}
    assert {"label": "Firefox", "clicks": 1} in body_7["top_browsers"]
    assert {"label": "Desktop", "clicks": 3} in body_7["top_devices"]
    assert {"label": "Mobile", "clicks": 1} in body_7["top_devices"]
    assert {"label": "github.com", "clicks": 2} in body_7["top_referers"]
    assert {"label": "Direct", "clicks": 1} in body_7["top_referers"]
    assert {"label": "Mac OS X", "clicks": 2} in body_7["top_os"]

    stats_30 = await client.get("/api/v1/links/stats1/stats?days=30", headers=headers)
    assert stats_30.status_code == 200
    body_30 = stats_30.json()
    assert body_30["period_days"] == 30
    assert body_30["total_clicks"] == 4
    assert sum(day["clicks"] for day in body_30["clicks_by_day"]) == 4

    invalid_days = await client.get("/api/v1/links/stats1/stats?days=14", headers=headers)
    assert invalid_days.status_code == 422
    assert invalid_days.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_stats_endpoint_enforces_auth_ownership_and_404(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Stats require authentication, enforce ownership (403), and return 404 if missing."""
    owner_headers, _ = await auth_user_factory("stats-owner@example.com", "StrongPass123!")
    other_headers, _ = await auth_user_factory("stats-other@example.com", "StrongPass123!")

    created = await client.post(
        "/api/v1/links",
        headers=owner_headers,
        json={"original_url": "https://example.com/private", "custom_alias": "priv1"},
    )
    assert created.status_code == 201

    unauth = await client.get("/api/v1/links/priv1/stats")
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "UNAUTHORIZED"

    forbidden = await client.get("/api/v1/links/priv1/stats", headers=other_headers)
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "LINK_FORBIDDEN"

    missing = await client.get("/api/v1/links/unknown99/stats", headers=owner_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "LINK_NOT_FOUND"


async def test_delete_link_cascades_click_events(
    app: FastAPI,
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Deleting a link cascades and removes all associated click_events rows."""
    headers, _ = await auth_user_factory("cascade@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/cascade", "custom_alias": "casc1"},
    )
    assert created.status_code == 201
    link_id = uuid.UUID(created.json()["id"])

    for _ in range(2):
        r = await client.get("/casc1", follow_redirects=False)
        assert r.status_code == 307

    async with app.state.session_factory() as session:
        before = list(
            (await session.execute(select(ClickEvent).where(ClickEvent.link_id == link_id)))
            .scalars()
            .all()
        )
    assert len(before) == 2

    deleted = await client.delete("/api/v1/links/casc1", headers=headers)
    assert deleted.status_code == 204

    async with app.state.session_factory() as session:
        after = list(
            (await session.execute(select(ClickEvent).where(ClickEvent.link_id == link_id)))
            .scalars()
            .all()
        )
    assert len(after) == 0


async def test_background_click_persistence_error_does_not_fail_redirect(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Redirect still succeeds with 307 even if background DB click persistence fails."""
    created = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/safe-redirect", "custom_alias": "safe1"},
    )
    assert created.status_code == 201

    async def fail_click_insert(self: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(ClickRepository, "create", fail_click_insert)

    redirect_resp = await client.get("/safe1", follow_redirects=False)
    assert redirect_resp.status_code == 307
    assert redirect_resp.headers["Location"] == "https://example.com/safe-redirect"


async def test_stats_endpoint_returns_zeros_for_link_without_clicks(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Stats for a link with zero clicks return 200 with zero totals and empty lists."""
    headers, _ = await auth_user_factory("empty-stats@example.com", "StrongPass123!")
    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.com/no-clicks", "custom_alias": "noclicks"},
    )
    assert created.status_code == 201

    resp = await client.get("/api/v1/links/noclicks/stats", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["short_code"] == "noclicks"
    assert body["total_clicks"] == 0
    assert body["period_days"] == 7
    assert body["clicks_by_day"] == []
    assert body["top_browsers"] == []
    assert body["top_os"] == []
    assert body["top_devices"] == []
    assert body["top_referers"] == []


def test_postgres_asyncpg_aggregation_sql_compilation() -> None:
    """PostgreSQL aggregation queries compile cleanly with alias GROUP BY/ORDER BY."""
    link_id = uuid.uuid4()
    dialect = pg_asyncpg.dialect()

    daily_stmt = ClickRepository.build_clicks_by_day_stmt(
        link_id,
        since=datetime.now(UTC) - timedelta(days=7),
        dialect_name="postgresql",
    )
    daily_sql = str(daily_stmt.compile(dialect=dialect))
    assert "date_trunc" in daily_sql
    assert "to_char" in daily_sql
    assert "GROUP BY day" in daily_sql
    assert "ORDER BY day ASC" in daily_sql

    breakdown_stmt = ClickRepository.build_top_breakdown_stmt(
        link_id,
        ClickEvent.referer,
        fallback_label="Direct",
    )
    breakdown_sql = str(breakdown_stmt.compile(dialect=dialect))
    assert "coalesce" in breakdown_sql
    assert "GROUP BY label" in breakdown_sql
    assert "ORDER BY clicks DESC, label ASC" in breakdown_sql
