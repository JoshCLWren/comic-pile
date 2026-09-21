"""Add partial indexes for queue pagination to optimize fetch_queue_page and fetch_completed_page.

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-21 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add partial indexes for queue pagination."""
    # Partial index for active threads only, matching the fetch_queue_page query:
    # WHERE user_id = $1 AND status = 'active'
    # ORDER BY is_blocked ASC, queue_position ASC, id ASC (for "position" sort)
    op.create_index(
        "ix_thread_user_active_queue_position",
        "threads",
        ["user_id", "is_blocked", "queue_position", "id"],
        unique=False,
        postgresql_where="status = 'active'",
    )

    # Partial index for completed threads only, matching the fetch_completed_page query
    # for "created" sort (which is the default for completed, and "position" maps to it):
    # WHERE user_id = $1 AND status = 'completed'
    # ORDER BY created_at DESC, id DESC
    op.create_index(
        "ix_thread_user_completed_created_id",
        "threads",
        ["user_id", "created_at", "id"],
        unique=False,
        postgresql_where="status = 'completed'",
    )

    # Partial index for completed threads for "title" sort:
    # WHERE user_id = $1 AND status = 'completed'
    # ORDER BY title ASC, id ASC
    op.create_index(
        "ix_thread_user_completed_title_id",
        "threads",
        ["user_id", "title", "id"],
        unique=False,
        postgresql_where="status = 'completed'",
    )


def downgrade() -> None:
    """Remove the partial indexes."""
    op.drop_index("ix_thread_user_active_queue_position", table_name="threads")
    op.drop_index("ix_thread_user_completed_created_id", table_name="threads")
    op.drop_index("ix_thread_user_completed_title_id", table_name="threads")