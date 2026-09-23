"""Add delivery_records table for cross-repository factory delivery ledger.

Revision ID: c86300000001
Revises: c86200000001
Create Date: 2026-09-23 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision: str = "c86300000001"
down_revision: str | None = "c86200000001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the delivery_records table.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "delivery_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_repository", sa.String(length=255), nullable=False),
        sa.Column("target_repository", sa.String(length=255), nullable=False),
        sa.Column("target_branch", sa.String(length=255), nullable=False),
        sa.Column("target_pr_number", sa.Integer(), nullable=True),
        sa.Column("target_merge_sha", sa.String(length=64), nullable=True),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("worker_id", sa.String(length=100), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'branch_created', 'pr_opened', 'merged', 'failed', 'released')",
            name="ck_delivery_status",
        ),
        sa.CheckConstraint(
            "target_repository IN ('JoshCLWren/comic-pile', 'JoshCLWren/Latticery')",
            name="ck_delivery_target_repo",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_delivery_record_source",
        "delivery_records",
        ["source_repository"],
    )
    op.create_index(
        "ix_delivery_record_target",
        "delivery_records",
        ["target_repository"],
    )


def downgrade() -> None:
    """Remove the delivery_records table.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_delivery_record_target", table_name="delivery_records")
    op.drop_index("ix_delivery_record_source", table_name="delivery_records")
    op.drop_table("delivery_records")
