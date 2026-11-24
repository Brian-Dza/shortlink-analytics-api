"""Health check endpoint verifying live PostgreSQL and Redis connectivity."""

import asyncio

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.core.database import check_db_connection
from app.core.exceptions import utc_timestamp
from app.core.redis import check_redis_connection
from app.schemas.common import HealthResponse, ServiceHealth

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
    summary="Check service and dependency health",
)
async def health_check(request: Request) -> JSONResponse:
    """Ping PostgreSQL and Redis concurrently and return 200 OK or 503 Degraded."""
    postgres_ok, redis_ok = await asyncio.gather(
        check_db_connection(request.app.state.db_engine),
        check_redis_connection(getattr(request.app.state, "redis", None)),
    )

    is_healthy = postgres_ok and redis_ok
    payload = HealthResponse(
        status="ok" if is_healthy else "degraded",
        services=ServiceHealth(
            postgres="up" if postgres_ok else "down",
            redis="up" if redis_ok else "down",
        ),
        timestamp=utc_timestamp(),
    )
    http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=http_status, content=payload.model_dump())
