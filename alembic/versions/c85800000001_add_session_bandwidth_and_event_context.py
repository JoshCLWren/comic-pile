"""Add event context metadata for Snooze bandwidth corrections.

Revision ID: c85800000001
Revises: h9i0j1k2l3m4
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85800000001"
down_revision: str | Sequence[str] | None = "h9i0j1k2l3m4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add optional decision-context metadata captured at event time."""
    op.add_column(
        "events",
        sa.Column("recommendation_context", sa.JSON(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column(
            "context",
            sa.JSON(),
            nullable=True,
            comment="Optional decision-context metadata captured at event time",
        ),
    )


def downgrade() -> None:
    """Remove event context metadata."""
    op.drop_column("events", "context")
    op.drop_column("events", "recommendation_context")
