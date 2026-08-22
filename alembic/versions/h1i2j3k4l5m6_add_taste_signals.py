"""Add Taste Bank signals table for Phase 7 discovery.

Revision ID: h1i2j3k4l5m6
Revises: c85400000001
Create Date: 2026-08-22 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h1i2j3k4l5m6"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create taste_signals table."""
    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_type", sa.String(length=20), nullable=False),
        sa.Column("feature_key", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_issue_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_thread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("affinity", sa.Float(), nullable=True),
        sa.Column("verdict", sa.String(length=20), nullable=False, server_default="inferred"),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("feature_type IN ('creator', 'character', 'team', 'publisher', 'era')", name="ck_taste_signal_feature_type"),
        sa.CheckConstraint("verdict IN ('inferred', 'confirmed', 'sometimes', 'rejected')", name="ck_taste_signal_verdict"),
        sa.UniqueConstraint("user_id", "feature_type", "feature_key", name="uq_taste_signal_user_feature"),
    )
    op.create_index("ix_taste_signal_user_id", "taste_signals", ["user_id"])
    op.create_index("ix_taste_signal_user_verdict", "taste_signals", ["user_id", "verdict"])
    op.create_index("ix_taste_signal_user_type_key", "taste_signals", ["user_id", "feature_type", "feature_key"])


def downgrade() -> None:
    """Drop taste_signals table."""
    op.drop_index("ix_taste_signal_user_type_key", table_name="taste_signals")
    op.drop_index("ix_taste_signal_user_verdict", table_name="taste_signals")
    op.drop_index("ix_taste_signal_user_id", table_name="taste_signals")
    op.drop_table("taste_signals")
