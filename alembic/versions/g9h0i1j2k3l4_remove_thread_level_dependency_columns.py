"""Remove thread-level dependency columns and constraints.

Revision ID: g9h0i1j2k3l4
Revises: f8a3b2c1d4e5
Create Date: 2026-04-14 08:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g9h0i1j2k3l4"
down_revision: str | Sequence[str] | None = "28148d574e9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop thread-level dependency columns and related constraints."""
    op.drop_constraint("uq_dependency_thread_edge", "dependencies", type_="unique")

    op.drop_constraint("ck_dependency_exactly_one_type", "dependencies", type_="check")

    op.drop_column("dependencies", "source_thread_id")
    op.drop_column("dependencies", "target_thread_id")

    op.alter_column("dependencies", "source_issue_id", existing_type=sa.Integer(), nullable=False)
    op.alter_column("dependencies", "target_issue_id", existing_type=sa.Integer(), nullable=False)

    op.execute(
        text(
            "ALTER TABLE dependencies ADD CONSTRAINT ck_dependency_exactly_one_type "
            "CHECK (source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL)"
        )
    )


def downgrade() -> None:
    """Restore thread-level dependency columns and constraints."""
    op.execute(text("ALTER TABLE dependencies DROP CONSTRAINT ck_dependency_exactly_one_type"))

    op.alter_column("dependencies", "source_issue_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column("dependencies", "target_issue_id", existing_type=sa.Integer(), nullable=True)

    op.add_column(
        "dependencies",
        sa.Column("target_thread_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "dependencies",
        sa.Column("source_thread_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "fk_dependencies_target_thread_id_threads",
        "dependencies",
        "threads",
        ["target_thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_dependencies_source_thread_id_threads",
        "dependencies",
        "threads",
        ["source_thread_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        text(
            "ALTER TABLE dependencies ADD CONSTRAINT ck_dependency_exactly_one_type "
            "CHECK ("
            "(source_thread_id IS NOT NULL AND target_thread_id IS NOT NULL "
            "AND source_issue_id IS NULL AND target_issue_id IS NULL) OR "
            "(source_thread_id IS NULL AND target_thread_id IS NULL "
            "AND source_issue_id IS NOT NULL AND target_issue_id IS NOT NULL)"
            ")"
        )
    )

    op.create_unique_constraint(
        "uq_dependency_thread_edge", "dependencies", ["source_thread_id", "target_thread_id"]
    )
