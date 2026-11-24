"""Business logic service for link creation, validation, and lifecycle management."""

import secrets
from datetime import UTC, datetime
from urllib.parse import urlparse

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    GoneException,
    NotFoundException,
)
from app.core.redis import cache_delete_link, cache_get_link, cache_set_link
from app.models.link import Link
from app.models.user import User
from app.repositories.link_repository import LinkRepository
from app.schemas.link import LinkCachePayload, LinkCreate, LinkUpdate

BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
SHORT_CODE_LENGTH = 7
MAX_GENERATION_RETRIES = 5
MAX_URL_LENGTH = 2048
RESERVED_ALIASES: frozenset[str] = frozenset(
    {
        "api",
        "health",
        "docs",
        "redoc",
        "openapi.json",
        "metrics",
        "favicon.ico",
        "static",
    }
)


def ensure_utc(value: datetime) -> datetime:
    """Normalize a datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class LinkService:
    """Coordinates short code generation, URL safety checks, and ownership CRUD."""

    def __init__(
        self,
        session: AsyncSession,
        link_repo: LinkRepository,
        settings: Settings,
        redis_client: Redis | None = None,
    ) -> None:
        self._session = session
        self._link_repo = link_repo
        self._settings = settings
        self._redis = redis_client

    @staticmethod
    def generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
        """Generate a cryptographically random Base62 short code."""
        return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))

    def validate_original_url(self, raw_url: str) -> str:
        """Validate URL syntax, length, safe HTTP/HTTPS scheme, and loop prevention."""
        cleaned = raw_url.strip()
        if not cleaned or len(cleaned) > MAX_URL_LENGTH:
            raise BadRequestException(
                "URL length must be between 1 and 2048 characters.",
                code="INVALID_URL",
            )
        if any(ch.isspace() for ch in cleaned):
            raise BadRequestException(
                "URL must not contain whitespace.",
                code="INVALID_URL",
            )

        parsed = urlparse(cleaned)
        if parsed.scheme.lower() not in {"http", "https"}:
            raise BadRequestException(
                "Only http and https URLs are allowed.",
                code="INVALID_URL_SCHEME",
            )
        if not parsed.hostname:
            raise BadRequestException(
                "URL must contain a valid hostname.",
                code="INVALID_URL",
            )
        if parsed.hostname.lower() == self._settings.base_host:
            raise BadRequestException(
                "Destination URL cannot point to the shortener domain.",
                code="REDIRECT_LOOP_NOT_ALLOWED",
            )

        return cleaned

    def validate_expires_at(self, expires_at: datetime | None) -> datetime | None:
        """Ensure optional expiration timestamps are normalized to UTC and in the future."""
        if expires_at is None:
            return None
        normalized = ensure_utc(expires_at)
        if normalized <= datetime.now(UTC):
            raise BadRequestException(
                "Expiration timestamp must be in the future.",
                code="INVALID_EXPIRATION",
            )
        return normalized

    def validate_custom_alias(self, alias: str) -> str:
        """Ensure custom aliases do not collide with reserved application routes."""
        if alias.lower() in RESERVED_ALIASES:
            raise BadRequestException(
                "This custom alias is reserved and cannot be used.",
                code="RESERVED_ALIAS",
            )
        return alias

    async def create_link(self, payload: LinkCreate, current_user: User | None) -> Link:
        """Create a new shortened link with either a custom alias or Base62 retry loop."""
        clean_url = self.validate_original_url(payload.original_url)
        expires_at = self.validate_expires_at(payload.expires_at)
        user_id = current_user.id if current_user is not None else None

        if payload.custom_alias is not None:
            alias = self.validate_custom_alias(payload.custom_alias)
            try:
                link = await self._link_repo.create(
                    short_code=alias,
                    original_url=clean_url,
                    user_id=user_id,
                    expires_at=expires_at,
                )
            except IntegrityError as exc:
                raise ConflictException(
                    "This custom alias is already in use.",
                    code="ALIAS_ALREADY_EXISTS",
                ) from exc

            await self._session.commit()
            return link

        for _ in range(MAX_GENERATION_RETRIES):
            code = self.generate_short_code()
            try:
                link = await self._link_repo.create(
                    short_code=code,
                    original_url=clean_url,
                    user_id=user_id,
                    expires_at=expires_at,
                )
            except IntegrityError:
                continue

            await self._session.commit()
            return link

        raise ConflictException(
            "Unable to generate a unique short code. Please retry.",
            code="SHORT_CODE_GENERATION_FAILED",
        )

    async def list_user_links(
        self,
        current_user: User,
        *,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Link], int]:
        """Return paginated links belonging to the authenticated user."""
        return await self._link_repo.list_by_user(
            current_user.id,
            is_active=is_active,
            page=page,
            page_size=page_size,
        )

    async def _get_owned_link(self, short_code: str, current_user: User) -> Link:
        """Retrieve a link and enforce owner-only access."""
        link = await self._link_repo.get_by_short_code(short_code)
        if link is None:
            raise NotFoundException("Short link not found.", code="LINK_NOT_FOUND")
        if link.user_id != current_user.id:
            raise ForbiddenException(
                "You do not have permission to manage this link.",
                code="LINK_FORBIDDEN",
            )
        return link

    async def update_link(
        self,
        short_code: str,
        payload: LinkUpdate,
        current_user: User,
    ) -> Link:
        """Partially update an owned link while distinguishing omitted vs null fields."""
        link = await self._get_owned_link(short_code, current_user)
        fields_set = payload.model_fields_set

        if "original_url" in fields_set:
            if payload.original_url is None:
                raise BadRequestException("original_url cannot be null.", code="INVALID_URL")
            link.original_url = self.validate_original_url(payload.original_url)

        if "is_active" in fields_set:
            if payload.is_active is None:
                raise BadRequestException("is_active cannot be null.", code="BAD_REQUEST")
            link.is_active = payload.is_active

        if "expires_at" in fields_set:
            link.expires_at = self.validate_expires_at(payload.expires_at)

        updated = await self._link_repo.save(link)
        await self._session.commit()
        await cache_delete_link(self._redis, short_code)
        return updated

    async def delete_link(self, short_code: str, current_user: User) -> None:
        """Delete an owned link and invalidate any cached redirect entry."""
        link = await self._get_owned_link(short_code, current_user)
        await self._link_repo.delete(link)
        await self._session.commit()
        await cache_delete_link(self._redis, short_code)

    def _compute_cache_ttl(self, expires_at: datetime | None) -> int:
        """Bound cache TTL by the link's remaining lifetime when expires_at is set."""
        default_ttl = self._settings.link_cache_ttl_seconds
        if expires_at is None:
            return default_ttl
        remaining = int((ensure_utc(expires_at) - datetime.now(UTC)).total_seconds())
        return max(0, min(default_ttl, remaining))

    async def resolve_short_code(self, short_code: str) -> LinkCachePayload:
        """Resolve short_code via Redis Cache-Aside with graceful PostgreSQL fallback."""
        cached = await cache_get_link(self._redis, short_code)
        if cached is not None:
            if not cached.is_active:
                await cache_delete_link(self._redis, short_code)
                raise NotFoundException(
                    "The requested short link does not exist.",
                    code="LINK_NOT_FOUND",
                )
            if cached.expires_at is not None and ensure_utc(cached.expires_at) <= datetime.now(UTC):
                await cache_delete_link(self._redis, short_code)
                raise GoneException(
                    "The requested short link has expired.",
                    code="LINK_EXPIRED",
                )
            return cached

        link = await self._link_repo.get_by_short_code(short_code)
        if link is None or not link.is_active:
            raise NotFoundException(
                "The requested short link does not exist.",
                code="LINK_NOT_FOUND",
            )
        if link.expires_at is not None and ensure_utc(link.expires_at) <= datetime.now(UTC):
            raise GoneException(
                "The requested short link has expired.",
                code="LINK_EXPIRED",
            )

        payload = LinkCachePayload(
            link_id=link.id,
            original_url=link.original_url,
            is_active=link.is_active,
            expires_at=ensure_utc(link.expires_at) if link.expires_at is not None else None,
        )
        ttl = self._compute_cache_ttl(payload.expires_at)
        if ttl > 0:
            await cache_set_link(self._redis, short_code, payload, ttl_seconds=ttl)

        return payload
