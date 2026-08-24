"""Add source_roll_event_id to events for roll-outcome linkage.

Revision ID: d4e5f6a7b8c9
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source_roll_event_id FK and index to events table."""
    op.add_column(
        "events",
        sa.Column(
            "source_roll_event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_event_source_roll_event_id",
        "events",
        ["source_roll_event_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove source_roll_event_id column and index."""
    op.drop_index("ix_event_source_roll_event_id", table_name="events")
    op.drop_column("events", "source_roll_event_id")
