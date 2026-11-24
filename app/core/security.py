"""Password hashing (Argon2id), salted IP hashing, and JWT utilities."""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import Settings
from app.core.exceptions import UnauthorizedException

_password_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its stored Argon2id hash."""
    return _password_hasher.verify(plain_password, hashed_password)


def hash_ip_address(ip_address: str, salt: str) -> str:
    """Anonymize an IP address with HMAC-SHA256 using an application salt."""
    return hmac.new(
        salt.encode("utf-8"),
        ip_address.strip().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_access_token(
    subject: str,
    settings: Settings,
    expires_delta: timedelta | None = None,
) -> tuple[str, int]:
    """Create a signed JWT access token and return (token, expires_in_seconds)."""
    now = datetime.now(UTC)
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.jwt_access_token_expire_minutes)
    )
    expire = now + delta
    payload: dict[str, object] = {
        "sub": subject,
        "type": "access",
        "iat": now,
        "exp": expire,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, max(1, int(delta.total_seconds()))


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Decode and validate a JWT access token, returning the user UUID subject."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedException(
            "Access token has expired.",
            code="TOKEN_EXPIRED",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedException(
            "Invalid authentication token.",
            code="INVALID_TOKEN",
        ) from exc

    if payload.get("type") != "access":
        raise UnauthorizedException("Invalid authentication token.", code="INVALID_TOKEN")

    try:
        return uuid.UUID(str(payload["sub"]))
    except (ValueError, KeyError) as exc:
        raise UnauthorizedException(
            "Invalid authentication token.",
            code="INVALID_TOKEN",
        ) from exc
