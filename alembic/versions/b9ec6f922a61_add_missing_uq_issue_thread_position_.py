"""add missing uq_issue_thread_position constraint

Revision ID: b9ec6f922a61
Revises: g9h0i1j2k3l4
Create Date: 2026-04-18 19:05:13.151054

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9ec6f922a61"
down_revision: str | Sequence[str] | None = "g9h0i1j2k3l4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()

    # Acquire advisory lock to prevent concurrent issue modifications during migration
    connection.execute(sa.text("SELECT pg_advisory_lock(1608198843946057679)"))

    try:
        # Fix any existing duplicate (thread_id, position) combinations
        # Only affects threads that actually have duplicates (well-formed threads untouched)
        # Preserves existing reading order by ordering by position, not id
        connection.execute(
            sa.text("""
            WITH duplicate_threads AS (
                -- Find threads that have duplicate positions
                SELECT thread_id
                FROM issues
                GROUP BY thread_id, position
                HAVING COUNT(*) > 1
            ),
            ranked_issues AS (
                -- Renumber positions within affected threads, preserving order
                SELECT 
                    id,
                    thread_id,
                    position,
                    ROW_NUMBER() OVER (PARTITION BY thread_id ORDER BY position, id) AS new_position
                FROM issues
                WHERE thread_id IN (SELECT thread_id FROM duplicate_threads)
            )
            UPDATE issues i
            SET position = ri.new_position
            FROM ranked_issues ri
            WHERE i.id = ri.id
            AND i.position != ri.new_position
        """)
        )

        # Create the unique constraint as DEFERRABLE INITIALLY DEFERRED
        # This matches the model declaration in app/models/issue.py
        op.create_unique_constraint(
            "uq_issue_thread_position",
            "issues",
            ["thread_id", "position"],
            deferrable=True,
            initially="DEFERRED",
        )
    finally:
        # Release advisory lock
        connection.execute(sa.text("SELECT pg_advisory_unlock(1608198843946057679)"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_issue_thread_position", "issues", type_="unique")
