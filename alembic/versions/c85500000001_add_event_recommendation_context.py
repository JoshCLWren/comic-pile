"""Add recommendation context snapshots to events.

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the nullable recommendation_context JSONB column to events."""
    op.add_column(
        "events",
        sa.Column("recommendation_context", JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Drop the recommendation_context column from events."""
    op.drop_column("events", "recommendation_context")
