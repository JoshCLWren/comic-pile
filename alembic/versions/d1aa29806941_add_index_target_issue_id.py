"""Add index on dependencies(target_issue_id) for blocked-thread joins.

Revision ID: d1aa29806941
Revises: c86300000001
Create Date: 2026-09-24 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1aa29806941"
down_revision: str | Sequence[str] | None = "c86300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add index on target_issue_id for blocked-thread join performance."""
    op.create_index(
        "ix_dependencies_target_issue_id",
        "dependencies",
        ["target_issue_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove index on target_issue_id."""
    op.drop_index("ix_dependencies_target_issue_id", table_name="dependencies")