"""Add recommendation context snapshots and Taste Bank signals.

Revision ID: c85500000001
Revises: c85400000001
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85500000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record recommendation context on events and add user taste signals."""
    op.add_column(
        "events",
        sa.Column("recommendation_context", sa.JSON(), nullable=True),
    )
    op.create_table(
        "user_taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("normalized_key", sa.String(length=200), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "verdict IN ('confirmed', 'inferred', 'rejected', 'sometimes')",
            name="ck_user_taste_signal_verdict",
        ),
        sa.UniqueConstraint(
            "user_id",
            "category",
            "normalized_key",
            name="uq_user_taste_signal_identity",
        ),
    )
    op.create_index(
        "ix_user_taste_signal_user_id",
        "user_taste_signals",
        ["user_id"],
    )


def downgrade() -> None:
    """Remove the taste signal table and event context snapshot column."""
    op.drop_index("ix_user_taste_signal_user_id", table_name="user_taste_signals")
    op.drop_table("user_taste_signals")
    op.drop_column("events", "recommendation_context")
