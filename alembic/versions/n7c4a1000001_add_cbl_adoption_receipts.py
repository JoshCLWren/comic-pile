"""Add unique CBL adoption receipts per user and source list.

Revision ID: n7c4a1000001
Revises: c25530000001
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n7c4a1000001"
down_revision: str | Sequence[str] | None = "c25530000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create cbl_adoption_receipts with a unique (user, list) claim.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "cbl_adoption_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cbl_source_list_id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["cbl_source_list_id"], ["cbl_source_lists.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["continuity_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "cbl_source_list_id",
            name="uq_cbl_adoption_receipt_user_list",
        ),
    )
    op.create_index(
        "ix_cbl_adoption_receipt_plan_id",
        "cbl_adoption_receipts",
        ["plan_id"],
    )


def downgrade() -> None:
    """Drop cbl_adoption_receipts.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_cbl_adoption_receipt_plan_id", table_name="cbl_adoption_receipts")
    op.drop_table("cbl_adoption_receipts")
