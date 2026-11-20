"""Add queue exclusion groups for bulk queue removal provenance.

Revision ID: s54350000001
Revises: c44050000002
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s54350000001"
down_revision: str | Sequence[str] | None = "c44050000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queue_exclusion_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('reading_list', 'reading_plan', 'crossover')",
            name="ck_queue_exclusion_groups_source_kind",
        ),
    )
    op.create_index(
        "ix_queue_exclusion_groups_user_id",
        "queue_exclusion_groups",
        ["user_id"],
    )
    op.add_column(
        "threads",
        sa.Column("queue_exclusion_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_threads_queue_exclusion_group_id",
        "threads",
        "queue_exclusion_groups",
        ["queue_exclusion_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_threads_queue_exclusion_group_id",
        "threads",
        ["queue_exclusion_group_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_threads_queue_exclusion_group_id", table_name="threads")
    op.drop_constraint(
        "fk_threads_queue_exclusion_group_id", "threads", type_="foreignkey"
    )
    op.drop_column("threads", "queue_exclusion_group_id")
    op.drop_index("ix_queue_exclusion_groups_user_id", table_name="queue_exclusion_groups")
    op.drop_table("queue_exclusion_groups")
