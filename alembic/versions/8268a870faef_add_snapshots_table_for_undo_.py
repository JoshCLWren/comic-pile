"""add snapshots table for undo functionality

Revision ID: 8268a870faef
Revises: e61b6cf6d89a
Create Date: 2026-01-07 12:31:03.985177

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8268a870faef"
down_revision: str | Sequence[str] | None = "e61b6cf6d89a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=True),
        sa.Column("thread_states", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_snapshot_session_id", "snapshots", ["session_id"])
    op.create_index("ix_snapshot_event_id", "snapshots", ["event_id"])
    op.create_index("ix_snapshot_created_at", "snapshots", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_snapshot_created_at", table_name="snapshots")
    op.drop_index("ix_snapshot_event_id", table_name="snapshots")
    op.drop_index("ix_snapshot_session_id", table_name="snapshots")
    op.drop_table("snapshots")
