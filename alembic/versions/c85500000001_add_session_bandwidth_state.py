"""Add ephemeral session bandwidth state for Phase 4 Snooze corrections.

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
    """Add ephemeral bandwidth columns to sessions table.

    These nullable columns track inferred session bandwidth, confidence,
    source, and the original launch prediction. They support Phase 4
    Snooze-as-session-correction without affecting existing rows.
    """
    op.add_column(
        "sessions",
        sa.Column(
            "inferred_bandwidth",
            sa.String(20),
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
            comment="Confidence in inferred bandwidth (0.0–1.0)",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "bandwidth_source",
            sa.String(20),
            nullable=True,
            comment="Source of bandwidth inference: launch, snooze, or manual",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "predicted_bandwidth",
            sa.String(20),
            nullable=True,
            comment="Original launch prediction for accuracy analysis",
        ),
    )


def downgrade() -> None:
    """Remove ephemeral bandwidth columns from sessions table."""
    op.drop_column("sessions", "predicted_bandwidth")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "inferred_bandwidth")
