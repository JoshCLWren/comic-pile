"""Add index on target_issue_id for blocked-thread joins.

Revision ID: add_target_issue_id_index
Revises: c86200000001
Create Date: 2026-09-23 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_target_issue_id_index"
down_revision: str | Sequence[str] | None = "c86200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add index on target_issue_id for reverse dependency lookups."""
    op.create_index(
        "ix_dependencies_target_issue_id",
        "dependencies",
        ["target_issue_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the index on target_issue_id."""
    op.drop_index("ix_dependencies_target_issue_id", table_name="dependencies")
