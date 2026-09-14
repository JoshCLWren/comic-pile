"""add custom CBL lists

Revision ID: d901cba10001
Revises: c86100000001
Create Date: 2026-09-14
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d901cba10001"
down_revision: str | Sequence[str] | None = "c86100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user-owned custom CBL list and ordered entry tables."""
    op.create_table(
        "custom_cbl_lists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_custom_cbl_lists_user_updated",
        "custom_cbl_lists",
        ["user_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "custom_cbl_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("list_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["list_id"], ["custom_cbl_lists.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("list_id", "issue_id", name="uq_custom_cbl_entry_issue"),
        sa.UniqueConstraint("list_id", "position", name="uq_custom_cbl_entry_position"),
    )
    op.create_index(
        "ix_custom_cbl_entries_issue",
        "custom_cbl_entries",
        ["issue_id"],
        unique=False,
    )
    op.create_index(
        "ix_custom_cbl_entries_list",
        "custom_cbl_entries",
        ["list_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop custom CBL persistence."""
    op.drop_index("ix_custom_cbl_entries_list", table_name="custom_cbl_entries")
    op.drop_index("ix_custom_cbl_entries_issue", table_name="custom_cbl_entries")
    op.drop_table("custom_cbl_entries")
    op.drop_index("ix_custom_cbl_lists_user_updated", table_name="custom_cbl_lists")
    op.drop_table("custom_cbl_lists")
