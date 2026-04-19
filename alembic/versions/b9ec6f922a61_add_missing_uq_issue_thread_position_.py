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
    # First, fix any existing duplicate (thread_id, position) combinations
    # by renumbering positions within each thread to be sequential
    connection = op.get_bind()

    # For each thread, renumber issues sequentially to eliminate duplicates
    # This ensures the unique constraint can be created successfully
    connection.execute(
        sa.text("""
        WITH ranked_issues AS (
            SELECT 
                id,
                thread_id,
                position,
                ROW_NUMBER() OVER (PARTITION BY thread_id ORDER BY id) AS new_position
            FROM issues
        )
        UPDATE issues i
        SET position = ri.new_position
        FROM ranked_issues ri
        WHERE i.id = ri.id
        AND i.position != ri.new_position
    """)
    )

    # Now create the unique constraint as DEFERRABLE INITIALLY DEFERRED
    # This matches the model declaration in app/models/issue.py
    op.create_unique_constraint(
        "uq_issue_thread_position",
        "issues",
        ["thread_id", "position"],
        deferrable="DEFERRABLE",
        initially="DEFERRED",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_issue_thread_position", "issues", type_="unique")
