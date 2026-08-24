"""Add ephemeral session bandwidth state columns.

Revision ID: c85500000001
Revises: d4e5f6a7b8c9
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add nullable bandwidth state columns to the sessions table."""
    op.add_column(
        "sessions",
        sa.Column(
            "predicted_bandwidth",
            sa.String(length=20),
            nullable=True,
            comment="Predicted bandwidth at session start: light, balanced, or deep",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "active_bandwidth",
            sa.String(length=20),
            nullable=True,
            comment="Current active bandwidth: light, balanced, or deep",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth_confidence",
            sa.Float(),
            nullable=True,
            comment="Confidence in the active bandwidth (0.0-1.0)",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth_source",
            sa.String(length=30),
            nullable=True,
            comment="Source of the bandwidth state: inferred, manual, snooze, or quiz",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth_version",
            sa.String(length=50),
            nullable=True,
            comment="Mode/algorithm version that produced the bandwidth state",
        ),
    )


def downgrade() -> None:
    """Remove the session bandwidth state columns."""
    op.drop_column("sessions", "bandwidth_version")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "active_bandwidth")
    op.drop_column("sessions", "predicted_bandwidth")
