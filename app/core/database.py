"""Async SQLAlchemy engine, session factory, declarative base, and health check."""

import asyncio
import logging

from sqlalchemy import MetaData, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings

logger = logging.getLogger(__name__)

# Deterministic constraint and index names prevent noisy or ambiguous Alembic diffs.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base declarative class shared by all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(settings: Settings) -> AsyncEngine:
    """Build a configured async SQLAlchemy engine with connection pooling."""
    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build an async session maker bound to the provided engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


async def dispose_db_engine(engine: AsyncEngine) -> None:
    """Close all pooled connections cleanly on application shutdown."""
    await engine.dispose()


async def check_db_connection(engine: AsyncEngine, timeout_seconds: float = 2.0) -> bool:
    """Verify live PostgreSQL connectivity within a bounded timeout."""

    async def _ping() -> None:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), timeout=timeout_seconds)
        return True
    except (SQLAlchemyError, OSError, TimeoutError) as exc:
        logger.warning("PostgreSQL health check failed: %s", type(exc).__name__)
        return False
