"""SQLAlchemy ORM model for asynchronous click telemetry events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.link import Link


class ClickEvent(Base):
    """Individual redirect click event stored for analytics aggregations."""

    __tablename__ = "click_events"
    __table_args__ = (Index("ix_click_events_link_id_clicked_at", "link_id", desc("clicked_at")),)

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    link_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("links.id", ondelete="CASCADE"),
        nullable=False,
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    browser: Mapped[str | None] = mapped_column(String(50), nullable=True)
    os: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    referer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    link: Mapped[Link] = relationship("Link", back_populates="click_events")
