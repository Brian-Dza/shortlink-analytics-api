"""SQLAlchemy ORM model for shortened URLs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, desc, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.click_event import ClickEvent
    from app.models.user import User


class Link(Base):
    """Shortened link mapping short_code -> original_url."""

    __tablename__ = "links"
    __table_args__ = (Index("ix_links_user_id_created_at", "user_id", desc("created_at")),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    short_code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    owner: Mapped[User | None] = relationship("User", back_populates="links")
    click_events: Mapped[list[ClickEvent]] = relationship(
        "ClickEvent",
        back_populates="link",
        passive_deletes=True,
    )
