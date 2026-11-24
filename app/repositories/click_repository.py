"""Data access repository for ClickEvent persistence and SQL analytics aggregations."""

import uuid
from datetime import datetime

from sqlalchemy import Select, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.click_event import ClickEvent
from app.schemas.analytics import ClickMetadata


class ClickRepository:
    """Encapsulates async inserts and aggregated metric queries on click_events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, link_id: uuid.UUID, metadata: ClickMetadata) -> ClickEvent:
        """Persist a single click telemetry event within the current transaction."""
        event = ClickEvent(
            link_id=link_id,
            clicked_at=metadata.clicked_at,
            browser=metadata.browser,
            os=metadata.os,
            device_type=metadata.device_type,
            referer=metadata.referer,
            ip_hash=metadata.ip_hash,
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def count_total(self, link_id: uuid.UUID) -> int:
        """Return total recorded clicks for a given link."""
        stmt = select(func.count(ClickEvent.id)).where(ClickEvent.link_id == link_id)
        total = (await self._session.execute(stmt)).scalar_one()
        return int(total)

    @staticmethod
    def build_clicks_by_day_stmt(
        link_id: uuid.UUID,
        *,
        since: datetime,
        dialect_name: str = "postgresql",
    ) -> Select[tuple[str, int]]:
        """Build the daily click aggregation query for PostgreSQL or SQLite."""
        if dialect_name == "postgresql":
            day_expr = func.to_char(
                func.date_trunc("day", func.timezone("UTC", ClickEvent.clicked_at)),
                "YYYY-MM-DD",
            )
        else:
            day_expr = func.strftime("%Y-%m-%d", ClickEvent.clicked_at)

        day_col = day_expr.label("day")
        clicks_col = func.count(ClickEvent.id).label("clicks")
        day_alias = literal_column("day")
        return (
            select(day_col, clicks_col)
            .where(ClickEvent.link_id == link_id, ClickEvent.clicked_at >= since)
            .group_by(day_alias)
            .order_by(day_alias.asc())
        )

    @staticmethod
    def build_top_breakdown_stmt(
        link_id: uuid.UUID,
        column: InstrumentedAttribute[str | None],
        *,
        limit: int = 5,
        fallback_label: str = "Unknown",
    ) -> Select[tuple[str, int]]:
        """Build the top-N breakdown aggregation query for a dimension column."""
        label_expr = func.coalesce(func.nullif(column, ""), fallback_label)
        label_col = label_expr.label("label")
        clicks_col = func.count(ClickEvent.id).label("clicks")
        label_alias = literal_column("label")
        clicks_alias = literal_column("clicks")
        return (
            select(label_col, clicks_col)
            .where(ClickEvent.link_id == link_id)
            .group_by(label_alias)
            .order_by(clicks_alias.desc(), label_alias.asc())
            .limit(limit)
        )

    async def clicks_by_day(
        self,
        link_id: uuid.UUID,
        *,
        since: datetime,
    ) -> list[tuple[str, int]]:
        """Aggregate click counts per UTC calendar day since the cutoff timestamp."""
        bind = self._session.get_bind()
        dialect_name = bind.dialect.name if bind is not None else "postgresql"
        stmt = self.build_clicks_by_day_stmt(link_id, since=since, dialect_name=dialect_name)
        rows = (await self._session.execute(stmt)).all()
        return [(str(row.day), int(row.clicks)) for row in rows]

    async def top_breakdown(
        self,
        link_id: uuid.UUID,
        column: InstrumentedAttribute[str | None],
        *,
        limit: int = 5,
        fallback_label: str = "Unknown",
    ) -> list[tuple[str, int]]:
        """Aggregate top N buckets for a dimension column with deterministic tie-breaking."""
        stmt = self.build_top_breakdown_stmt(
            link_id,
            column,
            limit=limit,
            fallback_label=fallback_label,
        )
        rows = (await self._session.execute(stmt)).all()
        return [(str(row.label), int(row.clicks)) for row in rows]
