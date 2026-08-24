"""Add ephemeral reading-intent state to sessions.

Revision ID: c85700000001
Revises: c85400000001
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85700000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable reading-intent session-state columns."""
    op.add_column("sessions", sa.Column("reading_intent", sa.String(length=20), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("reading_intent_source", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("reading_intent_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("reading_intent_version", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    """Drop the reading-intent session-state columns."""
    op.drop_column("sessions", "reading_intent_version")
    op.drop_column("sessions", "reading_intent_confidence")
    op.drop_column("sessions", "reading_intent_source")
    op.drop_column("sessions", "reading_intent")