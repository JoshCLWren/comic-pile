"""Add shared catalog identity tables and nullable reader-library links.

Revision ID: m5d300000001
Revises: f2a3b4c5d6e7
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m5d300000001"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create catalog_series and catalog_issues tables, add nullable FKs to threads and issues.

    Args:
        None.

    Returns:
        None.
    """
    # Create catalog_series table
    op.create_table(
        "catalog_series",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "canonical_external_identity_id",
            sa.Integer(),
            sa.ForeignKey("external_identities.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_series_external_identity",
        "catalog_series",
        ["canonical_external_identity_id"],
    )

    # Create catalog_issues table
    op.create_table(
        "catalog_issues",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "canonical_external_identity_id",
            sa.Integer(),
            sa.ForeignKey("external_identities.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "catalog_series_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_series.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_catalog_issues_external_identity",
        "catalog_issues",
        ["canonical_external_identity_id"],
    )
    op.create_index(
        "ix_catalog_issues_catalog_series",
        "catalog_issues",
        ["catalog_series_id"],
    )

    # Add catalog_series_id to threads table (nullable, SET NULL on delete)
    op.add_column(
        "threads",
        sa.Column(
            "catalog_series_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_series.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_thread_catalog_series", "threads", ["catalog_series_id"])

    # Add catalog_issue_id to issues table (nullable, SET NULL on delete)
    op.add_column(
        "issues",
        sa.Column(
            "catalog_issue_id",
            sa.BigInteger(),
            sa.ForeignKey("catalog_issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_issue_catalog_issue", "issues", ["catalog_issue_id"])


def downgrade() -> None:
    """Drop catalog identity tables and remove nullable FKs from threads and issues.

    Args:
        None.

    Returns:
        None.
    """
    # Remove catalog_issue_id from issues
    op.drop_index("ix_issue_catalog_issue", table_name="issues")
    op.drop_column("issues", "catalog_issue_id")

    # Remove catalog_series_id from threads
    op.drop_index("ix_thread_catalog_series", table_name="threads")
    op.drop_column("threads", "catalog_series_id")

    # Drop catalog_issues table
    op.drop_index("ix_catalog_issues_catalog_series", table_name="catalog_issues")
    op.drop_index("ix_catalog_issues_external_identity", table_name="catalog_issues")
    op.drop_table("catalog_issues")

    # Drop catalog_series table
    op.drop_index("ix_catalog_series_external_identity", table_name="catalog_series")
    op.drop_table("catalog_series")
