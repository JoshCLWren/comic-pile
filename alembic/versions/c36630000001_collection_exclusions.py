"""Add durable owner-scoped collection exclusions.

Revision ID: c36630000001
Revises: c36620000001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c36630000001"
down_revision: str | Sequence[str] | None = "c36620000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create additive storage without inferring or inserting exclusions."""
    op.create_table(
        "collection_exclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("external_volume_id", sa.String(100), nullable=True),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "num_nonnulls(external_volume_id, thread_id, issue_id) = 1 "
            "AND (provider IS NULL) = (external_volume_id IS NULL)",
            name="ck_collection_exclusion_exactly_one_target",
        ),
        sa.CheckConstraint(
            "(thread_id IS NULL OR thread_id > 0) AND (issue_id IS NULL OR issue_id > 0)",
            name="ck_collection_exclusion_positive_ids",
        ),
    )
    op.create_index(
        "uq_collection_exclusion_owner_volume", "collection_exclusions",
        ["user_id", "provider", "external_volume_id"],
        unique=True, postgresql_where=sa.text("external_volume_id IS NOT NULL"),
    )
    op.create_index(
        "uq_collection_exclusion_owner_thread", "collection_exclusions",
        ["user_id", "thread_id"], unique=True,
        postgresql_where=sa.text("thread_id IS NOT NULL"),
    )
    op.create_index(
        "uq_collection_exclusion_owner_issue", "collection_exclusions",
        ["user_id", "issue_id"], unique=True,
        postgresql_where=sa.text("issue_id IS NOT NULL"),
    )
    op.create_index(
        "ix_collection_exclusions_user_id", "collection_exclusions", ["user_id"]
    )


def downgrade() -> None:
    """Drop only the additive exclusion storage."""
    op.drop_index("ix_collection_exclusions_user_id", table_name="collection_exclusions")
    op.drop_index("uq_collection_exclusion_owner_issue", table_name="collection_exclusions")
    op.drop_index("uq_collection_exclusion_owner_thread", table_name="collection_exclusions")
    op.drop_index("uq_collection_exclusion_owner_volume", table_name="collection_exclusions")
    op.drop_table("collection_exclusions")
