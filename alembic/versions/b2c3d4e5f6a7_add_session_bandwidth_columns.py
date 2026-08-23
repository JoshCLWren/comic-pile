"""add session bandwidth columns

Revision ID: b2c3d4e5f6a7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-23 00:00:00.000000+00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add ephemeral bandwidth state columns to sessions table."""
    op.add_column(
        "sessions",
        sa.Column("predicted_bandwidth", sa.String(20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("active_bandwidth", sa.String(20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("bandwidth_confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("bandwidth_source", sa.String(20), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("bandwidth_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("bandwidth_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove ephemeral bandwidth state columns from sessions table."""
    op.drop_column("sessions", "bandwidth_updated_at")
    op.drop_column("sessions", "bandwidth_version")
    op.drop_column("sessions", "bandwidth_source")
    op.drop_column("sessions", "bandwidth_confidence")
    op.drop_column("sessions", "active_bandwidth")
    op.drop_column("sessions", "predicted_bandwidth")
