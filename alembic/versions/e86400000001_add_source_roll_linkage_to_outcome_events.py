"""Add source-roll linkage to outcome events.

Revision ID: e86400000001
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e86400000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add a nullable self-reference from outcome events to their origin roll."""
    op.add_column(
        "events",
        sa.Column("source_roll_event_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "events_source_roll_event_id_fkey",
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
    """Remove the source-roll linkage column, index, and constraint."""
    op.drop_index("ix_event_source_roll_event_id", table_name="events")
    op.drop_constraint(
        "events_source_roll_event_id_fkey",
        "events",
        type_="foreignkey",
    )
    op.drop_column("events", "source_roll_event_id")
