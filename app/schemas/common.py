"""Shared Pydantic schemas for errors and system health."""

from typing import Literal

from pydantic import BaseModel


class ValidationErrorDetail(BaseModel):
    """Sanitized field-level validation error item."""

    field: str
    message: str


class ErrorDetail(BaseModel):
    """Standardized error payload body."""

    code: str
    message: str
    timestamp: str
    details: list[ValidationErrorDetail] | None = None


class ErrorResponse(BaseModel):
    """Envelope returned on every API error response."""

    error: ErrorDetail


class ServiceHealth(BaseModel):
    """Connectivity state for required backing services."""

    postgres: Literal["up", "down"]
    redis: Literal["up", "down"]


class HealthResponse(BaseModel):
    """Response contract for GET /health."""

    status: Literal["ok", "degraded"]
    services: ServiceHealth
    timestamp: str


class PaginatedResponse[T](BaseModel):
    """Generic paginated list response contract."""

    items: list[T]
    total: int
    page: int
    page_size: int
    total_pages: int
