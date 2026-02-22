"""Add dependency edges and thread-level blocked flag.

Revision ID: f1a2b3c4d5e6
Revises: f8a3b2c1d4e5
Create Date: 2026-02-22 16:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "f8a3b2c1d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Apply dependency schema changes."""
    op.add_column(
        "threads",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_thread_user_status_blocked_position",
        "threads",
        ["user_id", "status", "is_blocked", "queue_position"],
        unique=False,
    )

    op.create_table(
        "dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_thread_id", sa.Integer(), nullable=False),
        sa.Column("target_thread_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_thread_id", "target_thread_id", name="uq_dependency_edge"),
    )


def downgrade() -> None:
    """Revert dependency schema changes."""
    op.drop_table("dependencies")
    op.drop_index("ix_thread_user_status_blocked_position", table_name="threads")
    op.drop_column("threads", "is_blocked")
