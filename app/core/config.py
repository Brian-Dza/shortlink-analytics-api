"""Application configuration loaded and validated via Pydantic Settings."""

from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed environment settings for the API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "shortlink-analytics-api"
    app_env: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = False
    base_url: str = "http://localhost:8000"
    render_external_url: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    database_url: str
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=100)
    db_pool_recycle: int = Field(default=1800, ge=60)

    redis_url: str
    link_cache_ttl_seconds: int = Field(default=86400, ge=60)

    jwt_secret_key: SecretStr = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, ge=5, le=1440)

    ip_hash_salt: SecretStr = Field(..., min_length=16)

    rate_limit_window_seconds: int = Field(default=60, ge=1)
    rate_limit_anon_max_requests: int = Field(default=10, ge=1)
    rate_limit_auth_max_requests: int = Field(default=30, ge=1)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Normalize PaaS PostgreSQL URLs to use the asyncpg driver."""
        if value.startswith("postgres://"):
            return f"postgresql+asyncpg://{value.removeprefix('postgres://')}"
        if value.startswith("postgresql://"):
            return f"postgresql+asyncpg://{value.removeprefix('postgresql://')}"
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must start with 'postgresql+asyncpg://'")
        return value

    @model_validator(mode="after")
    def apply_render_external_url(self) -> Self:
        """Adopt Render's external URL automatically when base_url is left at default."""
        if self.render_external_url and self.base_url == "http://localhost:8000":
            self.base_url = self.render_external_url.rstrip("/")
        return self

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        """Ensure Redis connection strings use redis:// or rediss://."""
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("redis_url must start with 'redis://' or 'rediss://'")
        return value

    @property
    def base_host(self) -> str:
        """Return the normalized lowercase hostname for self-redirect loop prevention."""
        parsed = urlparse(self.base_url)
        if not parsed.hostname:
            raise ValueError("base_url must contain a valid hostname")
        return parsed.hostname.lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance loaded from environment variables."""
    return Settings()  # type: ignore[call-arg]
