"""Add bandwidth_updated_at column to sessions table.

Revision ID: add_bandwidth_updated_at
Revises: 1690_session_timezone
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "add_bandwidth_updated_at"
down_revision: str | Sequence[str] | None = "1690_session_timezone"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add bandwidth_updated_at column to sessions table."""
    op.add_column(
        "sessions",
        sa.Column("bandwidth_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove bandwidth_updated_at column from sessions table."""
    op.drop_column("sessions", "bandwidth_updated_at")
