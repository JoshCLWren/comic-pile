"""Add durable thread creation idempotency receipts.

Revision ID: c36640000001
Revises: c36630000001
Create Date: 2026-10-16 00:00:00.000000

Double-clicking Create Series sent two identical POSTs that each created a
series (issue #3466). The receipts table gives the idempotency key a durable
unique home so retries converge on the first thread.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c36640000001"
down_revision: str | Sequence[str] | None = "c36630000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the thread_create_receipts table.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "thread_create_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "idempotency_key", name="uq_thread_create_receipt_user_key"
        ),
    )
    op.create_index(
        "ix_thread_create_receipt_user_id",
        "thread_create_receipts",
        ["user_id"],
    )
    op.create_index(
        "ix_thread_create_receipt_created_at",
        "thread_create_receipts",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop the thread_create_receipts table.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_thread_create_receipt_created_at", table_name="thread_create_receipts")
    op.drop_index("ix_thread_create_receipt_user_id", table_name="thread_create_receipts")
    op.drop_table("thread_create_receipts")
