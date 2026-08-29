"""Add cache_entries and cache_generations tables for always-on Postgres caching.

Revision ID: c85500000001
Revises: 83b5669f636c
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "83b5669f636c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create cache_entries and cache_generations tables."""
    op.create_table(
        "cache_entries",
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("value", JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("namespace", "cache_key"),
    )
    op.create_index(
        "ix_cache_entries_expires_at",
        "cache_entries",
        ["expires_at"],
    )
    op.create_table(
        "cache_generations",
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )


def downgrade() -> None:
    """Drop cache_entries and cache_generations tables."""
    op.drop_table("cache_generations")
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    op.drop_table("cache_entries")
