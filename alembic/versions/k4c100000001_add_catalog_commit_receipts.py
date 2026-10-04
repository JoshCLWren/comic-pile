"""Add durable catalog commit idempotency receipts.

Revision ID: k4c100000001
Revises: j1a2b3c4d5e6
Create Date: 2026-10-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k4c100000001"
down_revision: str | Sequence[str] | None = "j1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the catalog_commit_receipts table.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "catalog_commit_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("endpoint", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_catalog_commit_receipt_user_key"),
    )
    op.create_index(
        "ix_catalog_commit_receipt_user_id",
        "catalog_commit_receipts",
        ["user_id"],
    )
    op.create_index(
        "ix_catalog_commit_receipt_created_at",
        "catalog_commit_receipts",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop the catalog_commit_receipts table.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_catalog_commit_receipt_created_at", table_name="catalog_commit_receipts")
    op.drop_index("ix_catalog_commit_receipt_user_id", table_name="catalog_commit_receipts")
    op.drop_table("catalog_commit_receipts")