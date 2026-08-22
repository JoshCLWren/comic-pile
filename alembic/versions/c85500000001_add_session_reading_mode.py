"""Add ephemeral reading-mode columns to sessions.

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable bandwidth/intent/source columns to the sessions table."""
    op.add_column("sessions", sa.Column("reading_bandwidth", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("reading_intent", sa.String(length=16), nullable=True))
    op.add_column("sessions", sa.Column("reading_mode_source", sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Remove the reading-mode columns from the sessions table."""
    op.drop_column("sessions", "reading_mode_source")
    op.drop_column("sessions", "reading_intent")
    op.drop_column("sessions", "reading_bandwidth")
