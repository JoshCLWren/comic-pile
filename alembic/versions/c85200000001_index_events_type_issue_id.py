"""Index rate events by issue for bounded reader-context aggregation.

Revision ID: c85200000001
Revises: c85100000001
Create Date: 2026-08-17 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85200000001"
down_revision: str | Sequence[str] | None = "c85100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the rate-by-issue composite index on the events table."""
    op.create_index(
        "ix_event_type_issue_id",
        "events",
        ["type", "issue_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the rate-by-issue composite index."""
    op.drop_index("ix_event_type_issue_id", table_name="events")