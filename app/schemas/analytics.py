"""Pydantic schemas for click telemetry capture and aggregated analytics stats."""

from datetime import datetime
from enum import IntEnum

from pydantic import BaseModel


class StatsPeriodDays(IntEnum):
    """Supported rolling time windows (in days) for link analytics."""

    SEVEN = 7
    THIRTY = 30


class ClickMetadata(BaseModel):
    """In-memory sanitized click telemetry handed off to background persistence."""

    browser: str
    os: str
    device_type: str
    referer: str | None
    ip_hash: str
    clicked_at: datetime


class DailyClickCount(BaseModel):
    """Daily aggregated click total."""

    date: str
    clicks: int


class BreakdownItem(BaseModel):
    """Labeled metric bucket (browser, OS, device type, or referer)."""

    label: str
    clicks: int


class LinkStatsResponse(BaseModel):
    """Aggregated analytics payload returned by GET /api/v1/links/{short_code}/stats."""

    short_code: str
    original_url: str
    total_clicks: int
    period_days: int
    clicks_by_day: list[DailyClickCount]
    top_browsers: list[BreakdownItem]
    top_os: list[BreakdownItem]
    top_devices: list[BreakdownItem]
    top_referers: list[BreakdownItem]
