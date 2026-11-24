"""FastAPI application factory and lifespan resource management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.endpoints import health, redirect, ui
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import create_db_engine, create_session_factory, dispose_db_engine
from app.core.exceptions import register_exception_handlers
from app.core.redis import close_redis_client, create_redis_client

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _configure_logging(log_level: str) -> None:
    """Configure structured baseline logging without noisy overrides."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()
    _configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
        db_engine = create_db_engine(resolved_settings)
        session_factory = create_session_factory(db_engine)
        redis_client = create_redis_client(resolved_settings)

        fastapi_app.state.settings = resolved_settings
        fastapi_app.state.db_engine = db_engine
        fastapi_app.state.session_factory = session_factory
        fastapi_app.state.redis = redis_client

        try:
            yield
        finally:
            await close_redis_client(redis_client)
            await dispose_db_engine(db_engine)

    fastapi_app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    register_exception_handlers(fastapi_app)
    fastapi_app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    fastapi_app.include_router(health.router)
    fastapi_app.include_router(ui.router)
    fastapi_app.include_router(api_router)
    # Catch-all redirect route must be registered last so static/UI/API paths win.
    fastapi_app.include_router(redirect.router)
    return fastapi_app
