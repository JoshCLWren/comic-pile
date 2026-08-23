"""Add explicit roll-outcome decision linkage to events.

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
    """Link outcome events to their exact originating roll event."""
    op.add_column(
        "events",
        sa.Column("source_roll_event_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_source_roll_event_id_events",
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
    """Remove the explicit roll-outcome decision linkage."""
    op.drop_index("ix_event_source_roll_event_id", table_name="events")
    op.drop_constraint(
        "fk_events_source_roll_event_id_events",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "source_roll_event_id")
