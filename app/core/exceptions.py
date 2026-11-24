"""Domain exceptions and global sanitized JSON exception handlers."""

import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ErrorDetail, ErrorResponse, ValidationErrorDetail

logger = logging.getLogger(__name__)

_HTTP_STATUS_CODES: dict[int, str] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
    status.HTTP_403_FORBIDDEN: "FORBIDDEN",
    status.HTTP_404_NOT_FOUND: "RESOURCE_NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "RESOURCE_CONFLICT",
    status.HTTP_410_GONE: "RESOURCE_GONE",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMIT_EXCEEDED",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
}


def utc_timestamp() -> str:
    """Return an ISO-8601 UTC timestamp formatted with trailing Z."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class AppException(Exception):  # noqa: N818
    """Base application exception mapped to the standard JSON error contract."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


class BadRequestException(AppException):
    """Raised when the client sends a malformed or disallowed domain request."""

    def __init__(self, message: str, code: str = "BAD_REQUEST") -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, code=code, message=message)


class UnauthorizedException(AppException):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(
        self,
        message: str = "Authentication credentials are invalid or missing.",
        code: str = "UNAUTHORIZED",
    ) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=code,
            message=message,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    """Raised when an authenticated user lacks ownership or permission."""

    def __init__(
        self,
        message: str = "You do not have permission to access this resource.",
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, code=code, message=message)


class NotFoundException(AppException):
    """Raised when a requested resource cannot be found."""

    def __init__(self, message: str, code: str = "RESOURCE_NOT_FOUND") -> None:
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, code=code, message=message)


class ConflictException(AppException):
    """Raised when creating or updating a resource conflicts with existing state."""

    def __init__(self, message: str, code: str = "RESOURCE_CONFLICT") -> None:
        super().__init__(status_code=status.HTTP_409_CONFLICT, code=code, message=message)


class GoneException(AppException):
    """Raised when a resource existed previously but has expired."""

    def __init__(self, message: str, code: str = "RESOURCE_GONE") -> None:
        super().__init__(status_code=status.HTTP_410_GONE, code=code, message=message)


class RateLimitExceededException(AppException):
    """Raised when a client exceeds the configured request rate limit."""

    def __init__(
        self,
        retry_after: int,
        message: str = "Rate limit exceeded. Please retry later.",
    ) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="RATE_LIMIT_EXCEEDED",
            message=message,
            headers={"Retry-After": str(max(1, retry_after))},
        )


class ServiceUnavailableException(AppException):
    """Raised when a required downstream dependency is unavailable."""

    def __init__(self, message: str, code: str = "SERVICE_UNAVAILABLE") -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=code,
            message=message,
        )


def _error_json_response(
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    details: list[ValidationErrorDetail] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            timestamp=utc_timestamp(),
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(exclude_none=True),
        headers=headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers enforcing a consistent JSON error envelope."""

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        return _error_json_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        message = exc.detail if isinstance(exc.detail, str) else "HTTP request failed."
        return _error_json_response(
            status_code=exc.status_code,
            code=code,
            message=message,
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        _: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        details = [
            ValidationErrorDetail(
                field=".".join(str(part) for part in err.get("loc", ())),
                message=str(err.get("msg", "Invalid value")),
            )
            for err in exc.errors()
        ]
        return _error_json_response(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details=details,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled exception while processing %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return _error_json_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal error occurred.",
        )
