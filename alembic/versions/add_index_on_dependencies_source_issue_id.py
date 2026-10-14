"""Add index on dependencies.source_issue_id.

This index significantly speeds up blocking-info queries that join
Dependency.source_issue_id against Issues, such as
_get_blocked_thread_ids_uncached and _canonical_blocking_explanations.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "o8p9q0r1s2t3"
down_revision: str | None = "c36420000001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_dependencies_source_issue_id",
        "dependencies",
        ["source_issue_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_dependencies_source_issue_id", table_name="dependencies")
