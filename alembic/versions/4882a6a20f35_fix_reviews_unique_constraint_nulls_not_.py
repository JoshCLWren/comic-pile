"""Fix reviews unique constraint nulls not distinct

Revision ID: 4882a6a20f35
Revises: f616f65e0f1f
Create Date: 2026-04-05 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op


revision: str = "4882a6a20f35"
down_revision: str | Sequence[str] | None = "f616f65e0f1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace unique constraint with NULLS NOT DISTINCT version."""
    op.drop_constraint("uq_review_user_thread_issue", "reviews", type_="unique")
    op.execute(
        "CREATE UNIQUE INDEX uq_review_user_thread_issue "
        "ON reviews (user_id, thread_id, issue_id) NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    """Revert to standard unique constraint."""
    op.execute("DROP INDEX IF EXISTS uq_review_user_thread_issue")
    op.create_unique_constraint(
        "uq_review_user_thread_issue", "reviews", ["user_id", "thread_id", "issue_id"]
    )
