"""Add Postgres cache tables (cache_entries and cache_counters).

Revision ID: c85500000001
Revises: d3a1c2b4e5f6
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "d3a1c2b4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the cache_entries and cache_counters tables."""
    op.create_table(
        "cache_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        "ix_cache_entries_key",
        "cache_entries",
        ["key"],
    )
    op.create_index(
        "ix_cache_entries_expires_at",
        "cache_entries",
        ["expires_at"],
    )

    op.create_table(
        "cache_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(
        "ix_cache_counters_key",
        "cache_counters",
        ["key"],
    )


def downgrade() -> None:
    """Drop the cache tables."""
    op.drop_index("ix_cache_counters_key", table_name="cache_counters")
    op.drop_table("cache_counters")
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    op.drop_index("ix_cache_entries_key", table_name="cache_entries")
    op.drop_table("cache_entries")