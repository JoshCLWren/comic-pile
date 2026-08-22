"""Add ephemeral session-mode state columns to sessions.

Revision ID: a1f4c9d2e7b6
Revises: c85400000001
Create Date: 2026-08-22 23:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1f4c9d2e7b6"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable bandwidth/intent session-mode columns."""
    op.add_column("sessions", sa.Column("session_bandwidth", sa.String(length=20), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_source", sa.String(length=20), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_confidence", sa.Float(), nullable=True))
    op.add_column("sessions", sa.Column("session_intent", sa.String(length=20), nullable=True))
    op.add_column("sessions", sa.Column("intent_source", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Remove ephemeral session-mode columns."""
    op.drop_column("sessions", "intent_source")
    op.drop_column("sessions", "session_intent")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "session_bandwidth")
