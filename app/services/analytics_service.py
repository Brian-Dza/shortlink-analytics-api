"""Analytics telemetry parsing, background persistence, and link stats aggregation."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from user_agents import parse as parse_ua

from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.rate_limit import extract_client_ip
from app.core.security import hash_ip_address
from app.models.click_event import ClickEvent
from app.models.user import User
from app.repositories.click_repository import ClickRepository
from app.repositories.link_repository import LinkRepository
from app.schemas.analytics import (
    BreakdownItem,
    ClickMetadata,
    DailyClickCount,
    LinkStatsResponse,
)

logger = logging.getLogger(__name__)


def parse_user_agent(user_agent_header: str | None) -> tuple[str, str, str]:
    """Parse a User-Agent string into (browser, os, device_type)."""
    if not user_agent_header or not user_agent_header.strip():
        return ("Unknown", "Unknown", "Other")

    ua = parse_ua(user_agent_header)
    browser = (ua.browser.family or "Unknown")[:50]
    os_name = (ua.os.family or "Unknown")[:50]

    if ua.is_bot:
        device_type = "Bot"
    elif ua.is_mobile:
        device_type = "Mobile"
    elif ua.is_tablet:
        device_type = "Tablet"
    elif ua.is_pc:
        device_type = "Desktop"
    else:
        device_type = "Other"

    return (browser, os_name, device_type)


def normalize_referer(raw_referer: str | None) -> str | None:
    """Normalize HTTP Referer header to its lowercase hostname (or sanitized URL)."""
    if raw_referer is None:
        return None
    cleaned = raw_referer.strip()
    if not cleaned:
        return None

    parsed = urlparse(cleaned)
    if parsed.hostname:
        return parsed.hostname.lower()[:255]
    return cleaned[:2048]


def extract_click_metadata(request: Request, *, ip_hash_salt: str) -> ClickMetadata:
    """Extract and anonymize request telemetry in memory before sending the redirect."""
    browser, os_name, device_type = parse_user_agent(request.headers.get("User-Agent"))
    referer = normalize_referer(request.headers.get("Referer"))
    client_ip = extract_client_ip(request)
    ip_hash = hash_ip_address(client_ip, ip_hash_salt)

    return ClickMetadata(
        browser=browser,
        os=os_name,
        device_type=device_type,
        referer=referer,
        ip_hash=ip_hash,
        clicked_at=datetime.now(UTC),
    )


async def record_click_background(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    link_id: uuid.UUID,
    metadata: ClickMetadata,
) -> None:
    """Persist click telemetry in an isolated DB session without failing the redirect."""
    try:
        async with session_factory() as session:
            repo = ClickRepository(session)
            await repo.create(link_id=link_id, metadata=metadata)
            await session.commit()
    except Exception as exc:
        logger.exception(
            "Background click persistence failed for link_id=%s: %s",
            link_id,
            type(exc).__name__,
        )


class AnalyticsService:
    """Provides ownership-checked aggregated analytics for shortened links."""

    def __init__(
        self,
        link_repo: LinkRepository,
        click_repo: ClickRepository,
    ) -> None:
        self._link_repo = link_repo
        self._click_repo = click_repo

    async def get_link_stats(
        self,
        short_code: str,
        current_user: User,
        *,
        days: int = 7,
    ) -> LinkStatsResponse:
        """Return aggregated click metrics for a link owned by current_user."""
        link = await self._link_repo.get_by_short_code(short_code)
        if link is None:
            raise NotFoundException("Short link not found.", code="LINK_NOT_FOUND")
        if link.user_id != current_user.id:
            raise ForbiddenException(
                "You do not have permission to view analytics for this link.",
                code="LINK_FORBIDDEN",
            )

        since = datetime.now(UTC) - timedelta(days=days)

        # Execute sequentially because AsyncSession does not support concurrent queries.
        total_clicks = await self._click_repo.count_total(link.id)
        daily_rows = await self._click_repo.clicks_by_day(link.id, since=since)
        browser_rows = await self._click_repo.top_breakdown(
            link.id,
            ClickEvent.browser,
            fallback_label="Unknown",
        )
        os_rows = await self._click_repo.top_breakdown(
            link.id,
            ClickEvent.os,
            fallback_label="Unknown",
        )
        device_rows = await self._click_repo.top_breakdown(
            link.id,
            ClickEvent.device_type,
            fallback_label="Other",
        )
        referer_rows = await self._click_repo.top_breakdown(
            link.id,
            ClickEvent.referer,
            fallback_label="Direct",
        )

        return LinkStatsResponse(
            short_code=link.short_code,
            original_url=link.original_url,
            total_clicks=total_clicks,
            period_days=days,
            clicks_by_day=[DailyClickCount(date=day, clicks=clicks) for day, clicks in daily_rows],
            top_browsers=[
                BreakdownItem(label=label, clicks=clicks) for label, clicks in browser_rows
            ],
            top_os=[BreakdownItem(label=label, clicks=clicks) for label, clicks in os_rows],
            top_devices=[
                BreakdownItem(label=label, clicks=clicks) for label, clicks in device_rows
            ],
            top_referers=[
                BreakdownItem(label=label, clicks=clicks) for label, clicks in referer_rows
            ],
        )
