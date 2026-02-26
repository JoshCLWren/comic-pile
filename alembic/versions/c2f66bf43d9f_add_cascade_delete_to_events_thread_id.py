"""add_cascade_delete_to_events_thread_id

Revision ID: c2f66bf43d9f
Revises: 16471e927eea
Create Date: 2026-01-10 23:23:04.453764

"""

from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c2f66bf43d9f"
down_revision: str | Sequence[str] | None = "16471e927eea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_thread_id_fkey")
    op.execute(
        "ALTER TABLE events ADD CONSTRAINT events_thread_id_fkey "
        "FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_thread_id_fkey")
    op.execute(
        "ALTER TABLE events ADD CONSTRAINT events_thread_id_fkey "
        "FOREIGN KEY (thread_id) REFERENCES threads(id)"
    )
