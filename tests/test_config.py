"""Tests for PaaS database URL normalization and Render external URL detection."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings


def _make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://user:pass@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "jwt_secret_key": SecretStr("a" * 32),
        "ip_hash_salt": SecretStr("b" * 16),
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw_url", "expected_url"),
    [
        (
            "postgres://user:pass@db.internal:5432/app",
            "postgresql+asyncpg://user:pass@db.internal:5432/app",
        ),
        (
            "postgresql://user:pass@db.internal:5432/app",
            "postgresql+asyncpg://user:pass@db.internal:5432/app",
        ),
        (
            "postgresql+asyncpg://user:pass@db.internal:5432/app",
            "postgresql+asyncpg://user:pass@db.internal:5432/app",
        ),
    ],
)
def test_database_url_normalizes_paas_schemes(raw_url: str, expected_url: str) -> None:
    """postgres:// and postgresql:// URLs normalize to postgresql+asyncpg://."""
    settings = _make_settings(database_url=raw_url)
    assert settings.database_url == expected_url


def test_invalid_database_scheme_raises_validation_error() -> None:
    """Non-PostgreSQL connection URLs are rejected."""
    with pytest.raises(ValidationError):
        _make_settings(database_url="mysql://user:pass@localhost:3306/db")


def test_render_external_url_sets_default_base_url_and_host() -> None:
    """RENDER_EXTERNAL_URL populates base_url unless explicitly overridden."""
    auto_settings = _make_settings(
        render_external_url="https://shortlink-analytics-api.onrender.com/",
    )
    assert auto_settings.base_url == "https://shortlink-analytics-api.onrender.com"
    assert auto_settings.base_host == "shortlink-analytics-api.onrender.com"

    explicit_settings = _make_settings(
        base_url="https://sho.rt",
        render_external_url="https://shortlink-analytics-api.onrender.com",
    )
    assert explicit_settings.base_url == "https://sho.rt"
    assert explicit_settings.base_host == "sho.rt"
