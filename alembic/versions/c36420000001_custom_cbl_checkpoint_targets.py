"""Store durable target issue IDs for custom CBL checkpoints.

Revision ID: c36420000001
Revises: c34990000001
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c36420000001"
down_revision: str | Sequence[str] | None = "c34990000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add source metadata without compiling or changing any prerequisites."""
    op.add_column(
        "custom_cbl_entries",
        sa.Column("checkpoint_target_issue_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    # Freeze each legacy flag to its successor in this source list, never an
    # unrelated issue that happens to follow it in a target plan.
    op.execute(
        sa.text("""
        WITH targets AS (
            SELECT id, lead(issue_id) OVER (PARTITION BY list_id ORDER BY position) target_id
            FROM custom_cbl_entries
        )
        UPDATE custom_cbl_entries e
        SET checkpoint_target_issue_ids = CASE WHEN t.target_id IS NULL THEN '[]'::json
            ELSE json_build_array(t.target_id) END,
            is_checkpoint = t.target_id IS NOT NULL
        FROM targets t WHERE e.id=t.id AND e.is_checkpoint
    """)
    )


def downgrade() -> None:
    """Remove target metadata; existing canonical dependencies remain untouched."""
    op.drop_column("custom_cbl_entries", "checkpoint_target_issue_ids")
