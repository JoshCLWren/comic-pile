"""Add Taste Bank tables for inferred and user-confirmed taste signals.

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
    """Create the taste_signals and taste_evidence tables."""
    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_taste_signals_user_id_users", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(20), nullable=False),
        sa.Column("stable_key", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(300), nullable=False),
        sa.Column("inferred_affinity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_threads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("distinct_runs_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("user_verdict", sa.String(20), nullable=True),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_prompted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("prompt_suppressed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "signal_type", "stable_key",
            name="uq_taste_signal_user_type_key",
        ),
        sa.CheckConstraint(
            "signal_type IN ('creator', 'character', 'team', 'publisher', 'era')",
            name="ck_taste_signal_type",
        ),
        sa.CheckConstraint(
            "user_verdict IS NULL OR user_verdict IN "
            "('confirmed', 'sometimes', 'rejected')",
            name="ck_taste_signal_verdict",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_taste_signal_confidence",
        ),
        sa.CheckConstraint(
            "evidence_count >= 0",
            name="ck_taste_signal_evidence_count",
        ),
        sa.CheckConstraint(
            "distinct_threads_count >= 0",
            name="ck_taste_signal_distinct_threads",
        ),
        sa.CheckConstraint(
            "distinct_runs_count >= 0",
            name="ck_taste_signal_distinct_runs",
        ),
    )
    op.create_index(
        "ix_taste_signal_user_id", "taste_signals", ["user_id"]
    )
    op.create_index(
        "ix_taste_signal_user_confidence",
        "taste_signals", ["user_id", "confidence"],
    )

    op.create_table(
        "taste_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "taste_signal_id",
            sa.Integer(),
            sa.ForeignKey(
                "taste_signals.id",
                name="fk_taste_evidence_signal_id_taste_signals",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", name="fk_taste_evidence_user_id_users", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(20), nullable=False),
        sa.Column("stable_key", sa.String(200), nullable=False),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey(
                "events.id",
                name="fk_taste_evidence_event_id_events",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey(
                "threads.id",
                name="fk_taste_evidence_thread_id_threads",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey(
                "issues.id",
                name="fk_taste_evidence_issue_id_issues",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("observed_rating", sa.Float(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "taste_signal_id", "event_id",
            name="uq_taste_evidence_signal_event",
        ),
    )
    op.create_index(
        "ix_taste_evidence_user_id", "taste_evidence", ["user_id"]
    )
    op.create_index(
        "ix_taste_evidence_signal_id", "taste_evidence", ["taste_signal_id"]
    )
    op.create_index(
        "ix_taste_evidence_user_signal",
        "taste_evidence", ["user_id", "signal_type", "stable_key"],
    )
    op.create_index(
        "ix_taste_evidence_event_id", "taste_evidence", ["event_id"]
    )


def downgrade() -> None:
    """Drop the taste_evidence and taste_signals tables."""
    op.drop_index("ix_taste_evidence_event_id", table_name="taste_evidence")
    op.drop_index("ix_taste_evidence_user_signal", table_name="taste_evidence")
    op.drop_index("ix_taste_evidence_signal_id", table_name="taste_evidence")
    op.drop_index("ix_taste_evidence_user_id", table_name="taste_evidence")
    op.drop_table("taste_evidence")
    op.drop_index("ix_taste_signal_user_confidence", table_name="taste_signals")
    op.drop_index("ix_taste_signal_user_id", table_name="taste_signals")
    op.drop_table("taste_signals")