"""add_cascade_delete_to_snapshots_event_id

Revision ID: 16471e927eea
Revises: 408b0e691539
Create Date: 2026-01-10 23:00:37.888617

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "16471e927eea"
down_revision: Union[str, Sequence[str], None] = "408b0e691539"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_event_id_fkey")
    op.execute(
        "ALTER TABLE snapshots ADD CONSTRAINT snapshots_event_id_fkey "
        "FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE snapshots DROP CONSTRAINT IF EXISTS snapshots_event_id_fkey")
    op.execute(
        "ALTER TABLE snapshots ADD CONSTRAINT snapshots_event_id_fkey "
        "FOREIGN KEY (event_id) REFERENCES events(id)"
    )
