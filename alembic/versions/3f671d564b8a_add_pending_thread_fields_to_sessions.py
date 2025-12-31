"""Add pending_thread fields to sessions.

Revision ID: 3f671d564b8a
Revises: cdb492422a59
Create Date: 2025-12-30 15:47:43.870438

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f671d564b8a"
down_revision: str | Sequence[str] | None = "cdb492422a59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions",
        sa.Column("pending_thread_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("sessions", sa.Column("pending_thread_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "pending_thread_id")
    op.drop_column("sessions", "pending_thread_updated_at")
