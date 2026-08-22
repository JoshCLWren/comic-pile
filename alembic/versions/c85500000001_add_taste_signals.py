"""Add persistent taste signals for discovery prompts.

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
    """Create the taste signals table."""
    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("feature_type", sa.String(length=50), nullable=False),
        sa.Column("feature_key", sa.String(length=200), nullable=False),
        sa.Column("creator_role", sa.String(length=50), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_threads", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("affinity_delta", sa.Float(), nullable=False, server_default="0"),
        sa.Column("verdict", sa.String(length=20), nullable=True),
        sa.Column("verdict_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_taste_signals_user_identity",
        "taste_signals",
        ["user_id", "feature_type", "creator_role", "feature_key"],
    )
    op.create_index(
        "ix_taste_signals_user_verdict",
        "taste_signals",
        ["user_id", "verdict"],
    )


def downgrade() -> None:
    """Drop the taste signals table."""
    op.drop_index("ix_taste_signals_user_verdict", table_name="taste_signals")
    op.drop_index("ix_taste_signals_user_identity", table_name="taste_signals")
    op.drop_table("taste_signals")
