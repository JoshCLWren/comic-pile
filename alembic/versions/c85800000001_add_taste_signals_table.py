"""Add taste_signals table.

Revision ID: c85800000001
Revises: c85600000001
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c85800000001"
down_revision: str | Sequence[str] | None = "c85600000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the taste_signals table."""
    signal_types = ("creator", "character", "team", "publisher", "era")
    user_verdicts = ("confirmed", "sometimes", "rejected")

    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(length=20), nullable=False),
        sa.Column("external_key", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("affinity_estimate", sa.Float(), nullable=True),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "distinct_thread_count", sa.Integer(), nullable=False, server_default="0"
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
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="fk_taste_signal_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"signal_type IN ({', '.join(repr(v) for v in signal_types)})",
            name="ck_taste_signal_signal_type",
        ),
        sa.CheckConstraint(
            f"user_verdict IS NULL OR user_verdict IN "
            f"({', '.join(repr(v) for v in user_verdicts)})",
            name="ck_taste_signal_user_verdict",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_taste_signal_confidence_range",
        ),
        sa.CheckConstraint(
            "affinity_estimate IS NULL OR (affinity_estimate >= -1 AND affinity_estimate <= 1)",
            name="ck_taste_signal_affinity_range",
        ),
        sa.CheckConstraint(
            "evidence_count >= 0 AND distinct_thread_count >= 0",
            name="ck_taste_signal_evidence_non_negative",
        ),
        sa.UniqueConstraint(
            "user_id", "signal_type", "external_key", name="uq_taste_signal_user_key"
        ),
    )
    op.create_index(
        "ix_taste_signal_user_verdict",
        "taste_signals",
        ["user_id", "user_verdict"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the taste_signals table."""
    op.drop_index("ix_taste_signal_user_verdict", table_name="taste_signals")
    op.drop_table("taste_signals")