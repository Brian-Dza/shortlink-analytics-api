"""Tests for user registration, JWT login, and route authentication guards."""

import uuid
from datetime import timedelta

from httpx import AsyncClient

from app.core.config import Settings
from app.core.security import create_access_token, decode_access_token


async def test_register_user_success_normalizes_email_and_hides_password(
    client: AsyncClient,
) -> None:
    """Registering a user returns 201 with normalized email and no password hash."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "  User.One@Example.COM  ", "password": "StrongPassword123!"},
    )

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["id"])
    assert body["email"] == "user.one@example.com"
    assert "created_at" in body
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    """Registering an already existing email (case-insensitive) returns 409."""
    payload = {"email": "dup@example.com", "password": "StrongPassword123!"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/auth/register",
        json={"email": "DUP@example.com", "password": "AnotherPassword123!"},
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_invalid_payload_returns_422(client: AsyncClient) -> None:
    """Short passwords and invalid emails fail validation with standardized 422 JSON."""
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert len(body["error"]["details"]) == 2


async def test_login_success_returns_valid_jwt(
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    """Logging in with valid credentials returns a verifiable JWT access token."""
    register_resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "AlicePassword123!"},
    )
    assert register_resp.status_code == 201
    user_id = uuid.UUID(register_resp.json()["id"])

    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ALICE@example.com", "password": "AlicePassword123!"},
    )

    assert login_resp.status_code == 200
    body = login_resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == test_settings.jwt_access_token_expire_minutes * 60
    decoded_subject = decode_access_token(body["access_token"], test_settings)
    assert decoded_subject == user_id


async def test_login_wrong_credentials_returns_401(client: AsyncClient) -> None:
    """Wrong password and unknown email both return 401 INVALID_CREDENTIALS."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "BobPassword123!"},
    )

    wrong_pw = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "WrongPassword!"},
    )
    assert wrong_pw.status_code == 401
    assert wrong_pw.json()["error"]["code"] == "INVALID_CREDENTIALS"

    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "BobPassword123!"},
    )
    assert unknown_email.status_code == 401
    assert unknown_email.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_protected_endpoint_rejects_missing_invalid_and_expired_tokens(
    client: AsyncClient,
    test_settings: Settings,
) -> None:
    """Protected routes enforce valid non-expired Bearer JWT tokens."""
    missing = await client.get("/api/v1/links")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"

    non_bearer = await client.get(
        "/api/v1/links",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert non_bearer.status_code == 401
    assert non_bearer.json()["error"]["code"] == "UNAUTHORIZED"

    tampered = await client.get(
        "/api/v1/links",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert tampered.status_code == 401
    assert tampered.json()["error"]["code"] == "INVALID_TOKEN"

    expired_token, _ = create_access_token(
        subject=str(uuid.uuid4()),
        settings=test_settings,
        expires_delta=timedelta(seconds=-10),
    )
    expired = await client.get(
        "/api/v1/links",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert expired.status_code == 401
    assert expired.json()["error"]["code"] == "TOKEN_EXPIRED"

    ghost_token, _ = create_access_token(
        subject=str(uuid.uuid4()),
        settings=test_settings,
    )
    ghost = await client.get(
        "/api/v1/links",
        headers={"Authorization": f"Bearer {ghost_token}"},
    )
    assert ghost.status_code == 401
    assert ghost.json()["error"]["code"] == "USER_NOT_FOUND"
