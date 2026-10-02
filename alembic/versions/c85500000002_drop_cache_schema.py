"""Drop cache_entries, cache_generations, and cache_usage tables.

Revision ID: c85500000002
Revises: c85500000001
Create Date: 2026-10-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c85500000002"
down_revision: str | Sequence[str] | None = "c85500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop cache_entries, cache_generations, and cache_usage tables."""
    # Drop cache_usage table first (no foreign dependencies)
    op.drop_table("cache_usage")
    
    # Drop the index on cache_entries before dropping the table
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    
    # Drop cache_entries table
    op.drop_table("cache_entries")
    
    # Drop cache_generations table
    op.drop_table("cache_generations")


def downgrade() -> None:
    """Recreate cache_entries, cache_generations, and cache_usage tables."""
    # Recreate cache_generations table
    op.create_table(
        "cache_generations",
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )
    
    # Recreate cache_entries table
    op.create_table(
        "cache_entries",
        sa.Column("namespace", sa.String(length=255), nullable=False),
        sa.Column("cache_key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.JSONB(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("namespace", "cache_key"),
    )
    op.create_index(
        "ix_cache_entries_expires_at",
        "cache_entries",
        ["expires_at"],
    )
    
    # Recreate cache_usage table
    op.create_table(
        "cache_usage",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("commands", sa.BigInteger(), nullable=False, default=0),
        sa.PrimaryKeyConstraint("month"),
    )