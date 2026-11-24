"""Link management CRUD and analytics endpoints."""

import math

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    enforce_create_link_rate_limit,
    get_analytics_service,
    get_app_settings,
    get_current_user,
    get_link_service,
    get_optional_current_user,
)
from app.core.config import Settings
from app.models.user import User
from app.schemas.analytics import LinkStatsResponse, StatsPeriodDays
from app.schemas.common import PaginatedResponse
from app.schemas.link import LinkCreate, LinkResponse, LinkUpdate
from app.services.analytics_service import AnalyticsService
from app.services.link_service import LinkService

router = APIRouter(prefix="/links", tags=["Links"])


@router.post(
    "",
    response_model=LinkResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_create_link_rate_limit)],
    summary="Create a shortened link",
)
async def create_link(
    payload: LinkCreate,
    current_user: User | None = Depends(get_optional_current_user),
    link_service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_app_settings),
) -> LinkResponse:
    """Create a short link anonymously or on behalf of an authenticated user."""
    link = await link_service.create_link(payload, current_user)
    return LinkResponse.from_model(link, settings.base_url)


@router.get(
    "",
    response_model=PaginatedResponse[LinkResponse],
    status_code=status.HTTP_200_OK,
    summary="List authenticated user links",
)
async def list_links(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    is_active: bool | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    link_service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_app_settings),
) -> PaginatedResponse[LinkResponse]:
    """Return a paginated list of links owned by the authenticated user."""
    items, total = await link_service.list_user_links(
        current_user,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    total_pages = math.ceil(total / page_size) if total > 0 else 0
    return PaginatedResponse[LinkResponse](
        items=[LinkResponse.from_model(link, settings.base_url) for link in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get(
    "/{short_code}/stats",
    response_model=LinkStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve aggregated click analytics for an owned link",
)
async def get_link_stats(
    short_code: str,
    days: StatsPeriodDays = Query(default=StatsPeriodDays.SEVEN),
    current_user: User = Depends(get_current_user),
    analytics_service: AnalyticsService = Depends(get_analytics_service),
) -> LinkStatsResponse:
    """Return total clicks, daily breakdown, and top browsers/OS/devices/referers."""
    return await analytics_service.get_link_stats(short_code, current_user, days=int(days))


@router.patch(
    "/{short_code}",
    response_model=LinkResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an owned link",
)
async def update_link(
    short_code: str,
    payload: LinkUpdate,
    current_user: User = Depends(get_current_user),
    link_service: LinkService = Depends(get_link_service),
    settings: Settings = Depends(get_app_settings),
) -> LinkResponse:
    """Update destination URL, activation flag, or expiration on an owned link."""
    link = await link_service.update_link(short_code, payload, current_user)
    return LinkResponse.from_model(link, settings.base_url)


@router.delete(
    "/{short_code}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an owned link",
)
async def delete_link(
    short_code: str,
    current_user: User = Depends(get_current_user),
    link_service: LinkService = Depends(get_link_service),
) -> Response:
    """Permanently delete a link owned by the authenticated user."""
    await link_service.delete_link(short_code, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
