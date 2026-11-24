"""Data access repository for Link entities."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.link import Link


class LinkRepository:
    """Encapsulates SQLAlchemy async persistence operations for links."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        short_code: str,
        original_url: str,
        user_id: uuid.UUID | None,
        expires_at: datetime | None,
    ) -> Link:
        """Insert a new link using a savepoint to isolate short_code collisions."""
        link = Link(
            short_code=short_code,
            original_url=original_url,
            user_id=user_id,
            expires_at=expires_at,
        )
        async with self._session.begin_nested():
            self._session.add(link)
            await self._session.flush()
        await self._session.refresh(link)
        return link

    async def get_by_short_code(self, short_code: str) -> Link | None:
        """Fetch a link by its unique short_code."""
        stmt = select(Link).where(Link.short_code == short_code)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        is_active: bool | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Link], int]:
        """Return paginated links owned by user_id and total matching count."""
        filters = [Link.user_id == user_id]
        if is_active is not None:
            filters.append(Link.is_active.is_(is_active))

        count_stmt = select(func.count(Link.id)).where(*filters)
        total = int((await self._session.execute(count_stmt)).scalar_one())

        items_stmt = (
            select(Link)
            .where(*filters)
            .order_by(Link.created_at.desc(), Link.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list((await self._session.execute(items_stmt)).scalars().all())
        return items, total

    async def save(self, link: Link) -> Link:
        """Flush pending attribute modifications on an existing link."""
        await self._session.flush()
        await self._session.refresh(link)
        return link

    async def delete(self, link: Link) -> None:
        """Delete a link entity and flush the change within the active transaction."""
        await self._session.delete(link)
        await self._session.flush()
