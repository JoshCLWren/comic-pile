"""Add session bandwidth state and event context metadata.

Revision ID: c85700000001
Revises: c85400000001
Create Date: 2026-08-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85700000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ephemeral session bandwidth columns and event context metadata."""
    op.add_column(
        "sessions",
        sa.Column(
            "inferred_bandwidth",
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
            sa.String(length=20),
            nullable=True,
            comment="Source of the active bandwidth: launch, snooze, manual",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "predicted_bandwidth",
            sa.String(length=20),
            nullable=True,
            comment="Original launch prediction preserved for later accuracy analysis",
        ),
    )
    op.add_column(
        "events",
        sa.Column(
            "context",
            sa.JSON(),
            nullable=True,
            comment="Optional decision-context metadata captured at event time",
        ),
    )


def downgrade() -> None:
    """Remove session bandwidth columns and event context metadata."""
    op.drop_column("events", "context")
    op.drop_column("sessions", "predicted_bandwidth")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "inferred_bandwidth")
