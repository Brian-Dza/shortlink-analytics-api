"""Create click_events table with composite analytics index.

Revision ID: 0002_create_click_events
Revises: 0001_create_users_and_links
Create Date: 2026-11-23 18:22:30.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_create_click_events"
down_revision: str | Sequence[str] | None = "0001_create_users_and_links"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create click_events table and composite index (link_id, clicked_at DESC)."""
    op.create_table(
        "click_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("link_id", sa.Uuid(), nullable=False),
        sa.Column(
            "clicked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("browser", sa.String(length=50), nullable=True),
        sa.Column("os", sa.String(length=50), nullable=True),
        sa.Column("device_type", sa.String(length=20), nullable=True),
        sa.Column("referer", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["link_id"],
            ["links.id"],
            name=op.f("fk_click_events_link_id_links"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_click_events")),
    )
    op.create_index(
        "ix_click_events_link_id_clicked_at",
        "click_events",
        ["link_id", sa.text("clicked_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """Drop click_events index and table."""
    op.drop_index("ix_click_events_link_id_clicked_at", table_name="click_events")
    op.drop_table("click_events")
