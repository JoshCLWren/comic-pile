"""Add settings table.

Revision ID: add_settings_table
Revises: ec7d2cfc55f0
Create Date: 2026-01-01 23:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "add_settings_table"
down_revision: str | Sequence[str] | None = "ec7d2cfc55f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_gap_hours", sa.Integer(), nullable=False),
        sa.Column("start_die", sa.Integer(), nullable=False),
        sa.Column("rating_min", sa.Float(), nullable=False),
        sa.Column("rating_max", sa.Float(), nullable=False),
        sa.Column("rating_step", sa.Float(), nullable=False),
        sa.Column("rating_threshold", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("settings")
