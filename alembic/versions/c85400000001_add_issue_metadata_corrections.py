"""Add canonical issue metadata corrections.

Revision ID: c85400000001
Revises: c85300000001
Create Date: 2026-08-20 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85400000001"
down_revision: str | Sequence[str] | None = "c85300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the issue metadata corrections table."""
    op.create_table(
        "issue_metadata_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(length=100), nullable=False),
        sa.Column("provider_value", sa.Text(), nullable=True),
        sa.Column("canonical_value", sa.Text(), nullable=False),
        sa.Column(
            "provenance",
            sa.String(length=100),
            nullable=False,
            server_default="user_correction",
        ),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_issue_metadata_correction_created_by",
        "issue_metadata_corrections",
        ["created_by"],
    )
    op.create_index(
        "ix_issue_metadata_correction_issue_id",
        "issue_metadata_corrections",
        ["issue_id"],
    )


def downgrade() -> None:
    """Drop the issue metadata corrections table."""
    op.drop_index(
        "ix_issue_metadata_correction_issue_id",
        table_name="issue_metadata_corrections",
    )
    op.drop_index(
        "ix_issue_metadata_correction_created_by",
        table_name="issue_metadata_corrections",
    )
    op.drop_table("issue_metadata_corrections")
