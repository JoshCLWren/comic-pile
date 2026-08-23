"""Add roll linkage and decision-time recommendation context to events.

Introduces the Phase 0/1 observability columns required by the reading-effort
model:

- ``events.source_roll_event_id``: explicit link from an outcome event (rate)
  back to the exact originating roll event. Legacy rows keep NULL and are
  tolerated without fabricating links.
- ``events.recommendation_context``: versioned context snapshot recorded on
  roll events at decision time (currently the selected candidate's
  reading-effort estimate and its source).

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the source-roll linkage and recommendation-context columns."""
    op.add_column("events", sa.Column("source_roll_event_id", sa.Integer(), nullable=True))
    op.add_column("events", sa.Column("recommendation_context", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_event_source_roll_event_id",
        "events",
        "events",
        ["source_roll_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_event_source_roll_event_id",
        "events",
        ["source_roll_event_id"],
    )


def downgrade() -> None:
    """Remove the source-roll linkage and recommendation-context columns."""
    op.drop_index("ix_event_source_roll_event_id", table_name="events")
    op.drop_constraint("fk_event_source_roll_event_id", "events", type_="foreignkey")
    op.drop_column("events", "recommendation_context")
    op.drop_column("events", "source_roll_event_id")
