"""Add cache_usage table for durable month-to-date command accounting.

Revision ID: c86100000001
Revises: c86000000001
Create Date: 2026-09-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c86100000001"
down_revision = "c86000000001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the cache_usage table for durable command accounting."""
    op.create_table(
        "cache_usage",
        sa.Column("month", sa.String(7), nullable=False),
        sa.Column("commands", sa.BigInteger(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("month"),
    )


def downgrade() -> None:
    """Drop the cache_usage table."""
    op.drop_table("cache_usage")
