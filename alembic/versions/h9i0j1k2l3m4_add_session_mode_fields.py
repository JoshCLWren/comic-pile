"""Add session mode (bandwidth + intent) columns.

Revision ID: h9i0j1k2l3m4
Revises: 05f8245be920
Create Date: 2026-08-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h9i0j1k2l3m4"
down_revision: str | Sequence[str] | None = "05f8245be920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add session mode columns for bandwidth and intent tracking.

    Bandwidth state columns are already provided by c85600000001; this migration
    adds only the intent state and correction guidance columns.
    """
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
