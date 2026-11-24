"""Tests for link creation, Base62 collision retries, URL validation, and CRUD."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.services.link_service import BASE62_ALPHABET, LinkService


async def test_create_anonymous_link_generates_7_char_base62(client: AsyncClient) -> None:
    """Anonymous link creation returns 201 with a 7-char Base62 short_code."""
    response = await client.post(
        "/api/v1/links",
        json={"original_url": "https://docs.python.org/3/library/asyncio.html"},
    )

    assert response.status_code == 201
    body = response.json()
    assert len(body["short_code"]) == 7
    assert all(ch in BASE62_ALPHABET for ch in body["short_code"])
    assert body["short_url"] == f"http://testserver/{body['short_code']}"
    assert body["original_url"] == "https://docs.python.org/3/library/asyncio.html"
    assert body["user_id"] is None
    assert body["is_active"] is True


async def test_create_authenticated_link_with_custom_alias_and_conflict(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Authenticated users can attach custom aliases and collisions return 409."""
    headers, user = await auth_user_factory("creator@example.com", "CreatorPass123!")
    future_expiry = (datetime.now(UTC) + timedelta(days=7)).isoformat()

    created = await client.post(
        "/api/v1/links",
        headers=headers,
        json={
            "original_url": "https://fastapi.tiangolo.com/",
            "custom_alias": "FastAPI-01",
            "expires_at": future_expiry,
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["short_code"] == "FastAPI-01"
    assert body["short_url"] == "http://testserver/FastAPI-01"
    assert body["user_id"] == user["id"]
    assert body["expires_at"] is not None

    duplicate = await client.post(
        "/api/v1/links",
        headers=headers,
        json={"original_url": "https://example.org", "custom_alias": "FastAPI-01"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ALIAS_ALREADY_EXISTS"


@pytest.mark.parametrize("alias", ["health", "api", "docs", "redoc", "openapi.json"])
async def test_create_reserved_custom_alias_returns_400(
    client: AsyncClient,
    alias: str,
) -> None:
    """Reserved application route names cannot be claimed as custom aliases."""
    response = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com", "custom_alias": alias},
    )

    if alias == "openapi.json":
        assert response.status_code == 422
    else:
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "RESERVED_ALIAS"


async def test_create_link_retries_on_base62_collision(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Base62 generation collides with an existing code, service retries cleanly."""
    first = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/first", "custom_alias": "DupCode"},
    )
    assert first.status_code == 201

    candidates = iter(["DupCode", "Uniq123"])
    monkeypatch.setattr(
        LinkService,
        "generate_short_code",
        staticmethod(lambda length=7: next(candidates)),
    )

    second = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/second"},
    )

    assert second.status_code == 201
    assert second.json()["short_code"] == "Uniq123"


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "ftp://files.example.com/archive.zip",
        "not-a-valid-url",
    ],
)
async def test_create_link_rejects_dangerous_or_invalid_schemes(
    client: AsyncClient,
    bad_url: str,
) -> None:
    """Disallowed URL schemes such as javascript: or data: are rejected with 400."""
    response = await client.post("/api/v1/links", json={"original_url": bad_url})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_URL_SCHEME"


async def test_create_link_rejects_loop_too_long_url_and_past_expiration(
    client: AsyncClient,
) -> None:
    """Reject self-redirect loops, URLs > 2048 chars, and non-future expiration timestamps."""
    loop_resp = await client.post(
        "/api/v1/links",
        json={"original_url": "http://testserver/already-short"},
    )
    assert loop_resp.status_code == 400
    assert loop_resp.json()["error"]["code"] == "REDIRECT_LOOP_NOT_ALLOWED"

    too_long = "https://example.com/" + ("a" * 2040)
    long_resp = await client.post("/api/v1/links", json={"original_url": too_long})
    assert long_resp.status_code == 422
    assert long_resp.json()["error"]["code"] == "VALIDATION_ERROR"

    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    past_resp = await client.post(
        "/api/v1/links",
        json={"original_url": "https://example.com/past", "expires_at": past},
    )
    assert past_resp.status_code == 400
    assert past_resp.json()["error"]["code"] == "INVALID_EXPIRATION"


async def test_list_links_pagination_filter_and_user_isolation(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Users only see their own links with accurate pagination and is_active filtering."""
    headers_a, _ = await auth_user_factory("usera@example.com", "UserAPass123!")
    headers_b, _ = await auth_user_factory("userb@example.com", "UserBPass123!")

    codes_a: list[str] = []
    for idx in range(3):
        res = await client.post(
            "/api/v1/links",
            headers=headers_a,
            json={"original_url": f"https://example.com/a/{idx}"},
        )
        assert res.status_code == 201
        codes_a.append(res.json()["short_code"])

    deactivate = await client.patch(
        f"/api/v1/links/{codes_a[0]}",
        headers=headers_a,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200

    res_b = await client.post(
        "/api/v1/links",
        headers=headers_b,
        json={"original_url": "https://example.com/b/0"},
    )
    assert res_b.status_code == 201

    page1 = await client.get("/api/v1/links?page=1&page_size=2", headers=headers_a)
    assert page1.status_code == 200
    p1_body = page1.json()
    assert p1_body["total"] == 3
    assert p1_body["page"] == 1
    assert p1_body["page_size"] == 2
    assert p1_body["total_pages"] == 2
    assert len(p1_body["items"]) == 2

    page2 = await client.get("/api/v1/links?page=2&page_size=2", headers=headers_a)
    assert page2.status_code == 200
    assert len(page2.json()["items"]) == 1

    active_only = await client.get("/api/v1/links?is_active=true", headers=headers_a)
    assert active_only.status_code == 200
    assert active_only.json()["total"] == 2
    assert all(item["is_active"] is True for item in active_only.json()["items"])

    inactive_only = await client.get("/api/v1/links?is_active=false", headers=headers_a)
    assert inactive_only.status_code == 200
    assert inactive_only.json()["total"] == 1
    assert inactive_only.json()["items"][0]["short_code"] == codes_a[0]

    list_b = await client.get("/api/v1/links", headers=headers_b)
    assert list_b.status_code == 200
    assert list_b.json()["total"] == 1
    assert list_b.json()["items"][0]["short_code"] == res_b.json()["short_code"]


async def test_update_and_delete_link_ownership_enforcement(
    client: AsyncClient,
    auth_user_factory: Callable[[str, str], Awaitable[tuple[dict[str, str], dict[str, object]]]],
) -> None:
    """Only the owning user may PATCH or DELETE a link; others receive 403."""
    owner_headers, _ = await auth_user_factory("owner1@example.com", "OwnerPass123!")
    other_headers, _ = await auth_user_factory("other1@example.com", "OtherPass123!")
    future_expiry = (datetime.now(UTC) + timedelta(days=3)).isoformat()

    created = await client.post(
        "/api/v1/links",
        headers=owner_headers,
        json={
            "original_url": "https://example.com/initial",
            "custom_alias": "owned-slug",
            "expires_at": future_expiry,
        },
    )
    assert created.status_code == 201

    forbidden_patch = await client.patch(
        "/api/v1/links/owned-slug",
        headers=other_headers,
        json={"original_url": "https://evil.example.com"},
    )
    assert forbidden_patch.status_code == 403
    assert forbidden_patch.json()["error"]["code"] == "LINK_FORBIDDEN"

    forbidden_delete = await client.delete("/api/v1/links/owned-slug", headers=other_headers)
    assert forbidden_delete.status_code == 403
    assert forbidden_delete.json()["error"]["code"] == "LINK_FORBIDDEN"

    updated = await client.patch(
        "/api/v1/links/owned-slug",
        headers=owner_headers,
        json={
            "original_url": "https://example.com/updated",
            "is_active": False,
            "expires_at": None,
        },
    )
    assert updated.status_code == 200
    upd_body = updated.json()
    assert upd_body["original_url"] == "https://example.com/updated"
    assert upd_body["is_active"] is False
    assert upd_body["expires_at"] is None

    deleted = await client.delete("/api/v1/links/owned-slug", headers=owner_headers)
    assert deleted.status_code == 204

    missing_after_delete = await client.patch(
        "/api/v1/links/owned-slug",
        headers=owner_headers,
        json={"is_active": True},
    )
    assert missing_after_delete.status_code == 404
    assert missing_after_delete.json()["error"]["code"] == "LINK_NOT_FOUND"
