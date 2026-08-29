"""Add rolling_recommendation_context snapshot to events.

Revision ID: c85900000002
Revises: c85900000001
Create Date: 2026-08-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85900000002"
down_revision: str | Sequence[str] | None = "05f8245be921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add versioned recommendation-context snapshot column to events."""
    op.add_column(
        "events",
        sa.Column(
            "rolling_recommendation_context",
            sa.JSON(),
            nullable=True,
            comment="Versioned snapshot of recommendation context captured at roll decision time",
        ),
    )


def downgrade() -> None:
    """Remove rolling_recommendation_context column."""
    op.drop_column("events", "rolling_recommendation_context")
