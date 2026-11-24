"""Pydantic schemas for shortened link creation, updates, and responses."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from app.models.link import Link

ALIAS_PATTERN = r"^[A-Za-z0-9_-]{3,16}$"


class LinkCreate(BaseModel):
    """Input payload for creating a short link."""

    original_url: str = Field(..., min_length=1, max_length=2048)
    custom_alias: str | None = Field(
        default=None,
        min_length=3,
        max_length=16,
        pattern=ALIAS_PATTERN,
    )
    expires_at: datetime | None = None


class LinkUpdate(BaseModel):
    """Partial update payload for an existing short link."""

    original_url: str | None = Field(default=None, min_length=1, max_length=2048)
    is_active: bool | None = None
    expires_at: datetime | None = None


class LinkResponse(BaseModel):
    """Public short link resource representation."""

    id: uuid.UUID
    short_code: str
    short_url: str
    original_url: str
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
    user_id: uuid.UUID | None

    @classmethod
    def from_model(cls, link: Link, base_url: str) -> Self:
        """Build a response DTO computing the public short_url from base_url."""
        normalized_base = base_url.rstrip("/")
        return cls(
            id=link.id,
            short_code=link.short_code,
            short_url=f"{normalized_base}/{link.short_code}",
            original_url=link.original_url,
            is_active=link.is_active,
            expires_at=link.expires_at,
            created_at=link.created_at,
            user_id=link.user_id,
        )


class LinkCachePayload(BaseModel):
    """JSON payload cached in Redis under key link:{short_code}."""

    link_id: uuid.UUID
    original_url: str
    is_active: bool = True
    expires_at: datetime | None = None
