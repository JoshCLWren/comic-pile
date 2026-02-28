"""Add issue-level dependency columns and constraints.

Revision ID: a4c9d8e7f6b1
Revises: 58c2d0ee93f3
Create Date: 2026-02-28 11:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4c9d8e7f6b1"
down_revision: str | Sequence[str] | None = "58c2d0ee93f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("dependencies", sa.Column("source_issue_id", sa.Integer(), nullable=True))
    op.add_column("dependencies", sa.Column("target_issue_id", sa.Integer(), nullable=True))

    op.alter_column("dependencies", "source_thread_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("dependencies", "target_thread_id", existing_type=sa.Integer(), nullable=True)

    op.create_foreign_key(
        "fk_dependencies_source_issue_id_issues",
        "dependencies",
        "issues",
        ["source_issue_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_dependencies_target_issue_id_issues",
        "dependencies",
        "issues",
        ["target_issue_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("uq_dependency_edge", "dependencies", type_="unique")
    op.create_unique_constraint(
        "uq_dependency_thread_edge",
        "dependencies",
        ["source_thread_id", "target_thread_id"],
    )
    op.create_unique_constraint(
        "uq_dependency_issue_edge",
        "dependencies",
        ["source_issue_id", "target_issue_id"],
    )
    op.create_check_constraint(
        "ck_dependency_exactly_one_type",
        "dependencies",
        "(source_thread_id IS NOT NULL AND target_thread_id IS NOT NULL "
        "AND source_issue_id IS NULL AND target_issue_id IS NULL) OR "
        "(source_thread_id IS NULL AND target_thread_id IS NULL "
        "AND source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_dependency_exactly_one_type", "dependencies", type_="check")
    op.drop_constraint("uq_dependency_issue_edge", "dependencies", type_="unique")
    op.drop_constraint("uq_dependency_thread_edge", "dependencies", type_="unique")
    op.create_unique_constraint(
        "uq_dependency_edge",
        "dependencies",
        ["source_thread_id", "target_thread_id"],
    )

    op.drop_constraint("fk_dependencies_target_issue_id_issues", "dependencies", type_="foreignkey")
    op.drop_constraint("fk_dependencies_source_issue_id_issues", "dependencies", type_="foreignkey")

    op.alter_column("dependencies", "target_thread_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("dependencies", "source_thread_id", existing_type=sa.Integer(), nullable=False)

    op.drop_column("dependencies", "target_issue_id")
    op.drop_column("dependencies", "source_issue_id")
