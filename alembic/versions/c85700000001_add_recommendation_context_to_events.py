"""Add decision-time recommendation_context to roll events.

Introduces the Phase 1 observability column required by the reading-effort
model (issue #1705):

- ``events.recommendation_context``: versioned context snapshot recorded on
  roll events at decision time. It records the selected candidate's
  reading-effort estimate and its source so later analysis can compare the
  decision-time estimate against observed outcomes.

``events.source_roll_event_id`` already exists from migration
``d4e5f6a7b8c9``; this migration only adds the context payload column.

Revision ID: c85700000001
Revises: h9i0j1k2l3m4
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85700000001"
down_revision: str | Sequence[str] | None = "h9i0j1k2l3m4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the recommendation_context JSON column to events."""
    op.add_column("events", sa.Column("recommendation_context", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the recommendation_context column."""
    op.drop_column("events", "recommendation_context")
