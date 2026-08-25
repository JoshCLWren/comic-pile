"""Add recommendation_reason_codes to Event model for explanation system

Revision ID: f7e8d9c0b1a2
Revises: e61b6cf6d89a
Create Date: 2026-08-22 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7e8d9c0b1a2"
down_revision: str | Sequence[str] | None = "e61b6cf6d89a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add recommendation_reason_codes column to events table
    op.add_column("events", sa.Column("recommendation_reason_codes", ARRAY(sa.Text()), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove recommendation_reason_codes column from events table
    op.drop_column("events", "recommendation_reason_codes")