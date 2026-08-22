"""Add ephemeral reading-mode state to sessions.

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
    """Add bandwidth/intent session-mode columns and event context."""
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth",
            sa.String(length=20),
            nullable=False,
            server_default="balanced",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth_source",
            sa.String(length=20),
            nullable=False,
            server_default="inferred",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("bandwidth_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "intent",
            sa.String(length=20),
            nullable=False,
            server_default="balanced",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "intent_source",
            sa.String(length=20),
            nullable=False,
            server_default="inferred",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("intent_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "mode_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "consecutive_snoozes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("events", sa.Column("context", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the reading-mode columns."""
    op.drop_column("events", "context")
    op.drop_column("sessions", "consecutive_snoozes")
    op.drop_column("sessions", "mode_version")
    op.drop_column("sessions", "intent_confidence")
    op.drop_column("sessions", "intent_source")
    op.drop_column("sessions", "intent")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth")
