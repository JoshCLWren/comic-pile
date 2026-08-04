"""Add named dependency groups.

Revision ID: a613b7c9d201
Revises: d85468471b73
Create Date: 2026-08-04 01:20:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a613b7c9d201"
down_revision: str | Sequence[str] | None = "d85468471b73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create user-owned dependency groups and polymorphic memberships."""
    op.create_table(
        "dependency_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_dependency_groups_user_name"),
    )
    op.create_index("ix_dependency_groups_user_id", "dependency_groups", ["user_id"])
    op.create_table(
        "dependency_group_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "(thread_id IS NOT NULL AND issue_id IS NULL) OR "
            "(thread_id IS NULL AND issue_id IS NOT NULL)",
            name="ck_dependency_group_membership_one_target",
        ),
        sa.ForeignKeyConstraint(["group_id"], ["dependency_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_id", "issue_id", name="uq_dependency_group_issue"),
        sa.UniqueConstraint("group_id", "thread_id", name="uq_dependency_group_thread"),
    )
    op.create_index(
        "ix_dependency_group_memberships_group_id",
        "dependency_group_memberships",
        ["group_id"],
    )
    op.create_index(
        "ix_dependency_group_memberships_issue_id",
        "dependency_group_memberships",
        ["issue_id"],
    )
    op.create_index(
        "ix_dependency_group_memberships_thread_id",
        "dependency_group_memberships",
        ["thread_id"],
    )


def downgrade() -> None:
    """Remove named dependency group persistence."""
    op.drop_index(
        "ix_dependency_group_memberships_thread_id",
        table_name="dependency_group_memberships",
    )
    op.drop_index(
        "ix_dependency_group_memberships_issue_id",
        table_name="dependency_group_memberships",
    )
    op.drop_index(
        "ix_dependency_group_memberships_group_id",
        table_name="dependency_group_memberships",
    )
    op.drop_table("dependency_group_memberships")
    op.drop_index("ix_dependency_groups_user_id", table_name="dependency_groups")
    op.drop_table("dependency_groups")
