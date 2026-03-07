"""add index on issues position field

Revision ID: 6017d4c472e3
Revises: d5588f8456ab
Create Date: 2026-03-06 18:19:34.503705

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "6017d4c472e3"
down_revision: str | Sequence[str] | None = "d5588f8456ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Add index on (thread_id, position) to optimize list_issues queries.
    Critical for preventing sequential scans on position ORDER BY.
    Expected impact: eliminates seq_scan in list_issues EXPLAIN plans.
    """
    op.create_index("ix_issue_thread_position", "issues", ["thread_id", "position"], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    Remove the (thread_id, position) index.
    Restores previous query performance (slower list_issues).
    """
    op.drop_index("ix_issue_thread_position", table_name="issues")
