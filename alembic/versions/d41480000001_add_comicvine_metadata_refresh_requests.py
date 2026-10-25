"""Add durable ComicVine metadata refresh request queue.

Revision ID: d41480000001
Revises: c40080000001
Create Date: 2026-10-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d41480000001"
down_revision: str | Sequence[str] | None = "c40080000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable ComicVine metadata repair queue table.

    Args: None
    Returns: None
    """
    op.create_table(
        "comicvine_metadata_refresh_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_identity_id", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'running', 'completed', 'no_credits', 'deferred', 'failed')",
            name="ck_comicvine_metadata_refresh_state",
        ),
        sa.ForeignKeyConstraint(
            ["external_identity_id"],
            ["external_identities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_identity_id",
            name="uq_comicvine_metadata_refresh_identity",
        ),
    )
    op.create_index(
        "ix_comicvine_metadata_refresh_due",
        "comicvine_metadata_refresh_requests",
        ["state", "next_attempt_at"],
    )


def downgrade() -> None:
    """Drop the durable ComicVine metadata repair queue table.

    Args: None
    Returns: None
    """
    op.drop_index(
        "ix_comicvine_metadata_refresh_due",
        table_name="comicvine_metadata_refresh_requests",
    )
    op.drop_table("comicvine_metadata_refresh_requests")
