"""Add durable database-backed release ledger.

Revision ID: c84900000001
Revises: c84800000001
Create Date: 2026-08-11 09:58:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c84900000001"
down_revision: str | Sequence[str] | None = "c84800000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the releases table and deterministic publication index.

    Args:
        None.

    Returns:
        None.
    """
    op.create_table(
        "releases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_repository", sa.String(length=255), nullable=False),
        sa.Column("source_pr_number", sa.Integer(), nullable=True),
        sa.Column("source_merge_sha", sa.String(length=64), nullable=True),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('public', 'internal')",
            name="ck_release_visibility",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'retracted')",
            name="ck_release_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_repository",
            "source_pr_number",
            name="uq_release_source_pr",
        ),
        sa.UniqueConstraint(
            "source_repository",
            "source_merge_sha",
            name="uq_release_source_merge_sha",
        ),
    )
    op.create_index(
        "ix_release_published_order",
        "releases",
        ["status", "visibility", "released_at", "sort_order", "id"],
    )


def downgrade() -> None:
    """Remove the durable release ledger.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_index("ix_release_published_order", table_name="releases")
    op.drop_table("releases")
