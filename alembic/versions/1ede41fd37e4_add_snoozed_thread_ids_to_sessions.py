"""add_snoozed_thread_ids_to_sessions

Revision ID: 1ede41fd37e4
Revises: b0e386559bcb
Create Date: 2026-01-24 18:46:04.322654

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1ede41fd37e4"
down_revision: str | Sequence[str] | None = "b0e386559bcb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("snoozed_thread_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "snoozed_thread_ids")
