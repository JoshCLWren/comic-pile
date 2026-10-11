"""Add denormalized thread_title to events for deleted-thread history display.

Revision ID: 3265_add_thread_title
Revises: e913be4e091d
Create Date: 2026-10-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3265_add_thread_title"
down_revision: str | Sequence[str] | None = "e913be4e091d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the thread_title column and backfill titles for events that still resolve."""
    op.add_column("events", sa.Column("thread_title", sa.String(200), nullable=True))
    # Events recorded before this migration have no frozen title. Copy the current
    # thread title in now so a later thread deletion still renders a real name
    # instead of the unavailable placeholder. Roll events key off
    # selected_thread_id; every other event type keys off thread_id.
    op.execute(
        """
        UPDATE events AS e
        SET thread_title = t.title
        FROM threads AS t
        WHERE e.thread_title IS NULL
          AND t.id = COALESCE(e.selected_thread_id, e.thread_id)
        """
    )


def downgrade() -> None:
    """Remove thread_title column from events table."""
    op.drop_column("events", "thread_title")