"""Add session mode (bandwidth + intent) columns.

Revision ID: h9i0j1k2l3m4
Revises: d4e5f6a7b8c9
Create Date: 2026-08-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h9i0j1k2l3m4"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add session mode columns for bandwidth and intent tracking."""
    op.add_column("sessions", sa.Column("active_bandwidth", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("predicted_bandwidth", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_confidence", sa.Float(), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_source", sa.String(30), nullable=True))
    op.add_column("sessions", sa.Column("bandwidth_version", sa.String(50), nullable=True))
    op.add_column("sessions", sa.Column("active_intent", sa.String(30), nullable=True))
    op.add_column("sessions", sa.Column("predicted_intent", sa.String(30), nullable=True))
    op.add_column("sessions", sa.Column("intent_confidence", sa.Float(), nullable=True))
    op.add_column("sessions", sa.Column("intent_source", sa.String(30), nullable=True))
    op.add_column("sessions", sa.Column("intent_version", sa.String(50), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("session_mode_correction_guidance", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove session mode columns."""
    op.drop_column("sessions", "session_mode_correction_guidance")
    op.drop_column("sessions", "intent_version")
    op.drop_column("sessions", "intent_source")
    op.drop_column("sessions", "intent_confidence")
    op.drop_column("sessions", "predicted_intent")
    op.drop_column("sessions", "active_intent")
    op.drop_column("sessions", "bandwidth_version")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "predicted_bandwidth")
    op.drop_column("sessions", "active_bandwidth")
