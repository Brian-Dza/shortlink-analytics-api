"""FastAPI dependency providers for database sessions, Redis, services, and auth."""

from collections.abc import AsyncGenerator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import UnauthorizedException
from app.core.rate_limit import check_rate_limit, extract_client_ip
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.click_repository import ClickRepository
from app.repositories.link_repository import LinkRepository
from app.repositories.user_repository import UserRepository
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService
from app.services.link_service import LinkService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a scoped async SQLAlchemy session from the app state factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


def get_redis(request: Request) -> Redis | None:
    """Return the shared async Redis client stored on application state."""
    return getattr(request.app.state, "redis", None)


def get_app_settings(request: Request) -> Settings:
    """Return the active Settings instance stored on application state."""
    return request.app.state.settings


def get_auth_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> AuthService:
    """Build an AuthService wired with its repository and settings."""
    return AuthService(session=db, user_repo=UserRepository(db), settings=settings)


def get_link_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
    redis_client: Redis | None = Depends(get_redis),
) -> LinkService:
    """Build a LinkService wired with its repository, settings, and Redis cache."""
    return LinkService(
        session=db,
        link_repo=LinkRepository(db),
        settings=settings,
        redis_client=redis_client,
    )


def get_analytics_service(db: AsyncSession = Depends(get_db)) -> AnalyticsService:
    """Build an AnalyticsService wired with link and click repositories."""
    return AnalyticsService(
        link_repo=LinkRepository(db),
        click_repo=ClickRepository(db),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> User:
    """Require a valid Bearer JWT and return the corresponding User entity."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedException()

    user_id = decode_access_token(credentials.credentials, settings)
    return await auth_service.get_user_by_id(user_id)


async def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> User | None:
    """Resolve an authenticated user if Authorization is supplied, else return None."""
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        raise UnauthorizedException()

    user_id = decode_access_token(credentials.credentials, settings)
    return await auth_service.get_user_by_id(user_id)


async def enforce_create_link_rate_limit(
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
    redis_client: Redis | None = Depends(get_redis),
    settings: Settings = Depends(get_app_settings),
) -> None:
    """Enforce anonymous (IP) or authenticated (user) rate limits on link creation."""
    if current_user is not None:
        identifier = f"user:{current_user.id}"
        max_requests = settings.rate_limit_auth_max_requests
    else:
        identifier = f"anon:{extract_client_ip(request)}"
        max_requests = settings.rate_limit_anon_max_requests

    await check_rate_limit(
        redis_client=redis_client,
        scope="create_link",
        identifier=identifier,
        max_requests=max_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
