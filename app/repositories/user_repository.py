"""Data access repository for User entities."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Encapsulates SQLAlchemy async persistence operations for users."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Fetch a user by primary key UUID."""
        stmt = select(User).where(User.id == user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Fetch a user by normalized email address."""
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, *, email: str, hashed_password: str) -> User:
        """Insert a new user within a savepoint so IntegrityError stays isolated."""
        user = User(email=email, hashed_password=hashed_password)
        async with self._session.begin_nested():
            self._session.add(user)
            await self._session.flush()
        await self._session.refresh(user)
        return user
