"""Add the Taste Bank taste signals table.

Revision ID: 83b5669f636c
Revises: d4e5f6a7b8c9
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "83b5669f636c"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the taste signals table."""
    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_taste_signal_user_id_users", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(length=20), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("affinity_estimate", sa.Float(), nullable=True),
        sa.Column(
            "evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "distinct_thread_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("user_verdict", sa.String(length=20), nullable=True),
        sa.Column("verdict_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_suppressed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "signal_type IN ('creator', 'character', 'team', 'publisher', 'era')",
            name="ck_taste_signal_signal_type",
        ),
        sa.CheckConstraint(
            "user_verdict IS NULL OR user_verdict IN "
            "('confirmed', 'sometimes', 'rejected')",
            name="ck_taste_signal_user_verdict",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_taste_signal_confidence_range",
        ),
        sa.CheckConstraint(
            "affinity_estimate IS NULL OR "
            "(affinity_estimate >= -1 AND affinity_estimate <= 1)",
            name="ck_taste_signal_affinity_range",
        ),
        sa.CheckConstraint(
            "evidence_count >= 0 AND distinct_thread_count >= 0",
            name="ck_taste_signal_evidence_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "signal_type", "external_key", name="uq_taste_signal_user_key"),
    )
    op.create_index(
        "ix_taste_signal_user_verdict",
        "taste_signals",
        ["user_id", "user_verdict"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the taste signals table."""
    op.drop_index("ix_taste_signal_user_verdict", table_name="taste_signals")
    op.drop_table("taste_signals")
