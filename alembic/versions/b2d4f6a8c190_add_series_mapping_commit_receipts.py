"""Add durable series-mapping commit receipts.

Revision ID: b2d4f6a8c190
Revises: d1aa29806941
Create Date: 2026-09-27 07:40:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c190"
down_revision: str | Sequence[str] | None = "d1aa29806941"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the durable idempotency store for series-mapping commits.

    Args: None
    Returns: None
    """
    op.create_table(
        "series_mapping_commit_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_series_external_id", sa.String(length=100), nullable=False),
        sa.Column("origin_issue_id", sa.Integer(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_series_mapping_commit_receipt_key"),
    )
    op.create_index(
        "ix_series_mapping_commit_receipt_user_id",
        "series_mapping_commit_receipts",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the durable series-mapping commit idempotency store.

    Args: None
    Returns: None
    """
    op.drop_index(
        "ix_series_mapping_commit_receipt_user_id",
        table_name="series_mapping_commit_receipts",
    )
    op.drop_table("series_mapping_commit_receipts")
