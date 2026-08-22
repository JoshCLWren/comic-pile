"""Add Postgres cache tables (cache_entries and cache_generations).

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
    """Create the cache_entries and cache_generations tables."""
    op.create_table(
        "cache_entries",
        sa.Column("key", sa.String(length=500), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("ttl", sa.Integer(), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        "ix_cache_entries_expires_at",
        "cache_entries",
        ["expires_at"],
    )

    op.create_table(
        "cache_generations",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    """Drop the cache tables."""
    op.drop_table("cache_generations")
    op.drop_index("ix_cache_entries_expires_at", table_name="cache_entries")
    op.drop_table("cache_entries")