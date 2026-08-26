"""Add the taste evidence table for rebuildable Taste Bank inference.

Revision ID: c85700000001
Revises: c85800000001
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85700000001"
down_revision: str | Sequence[str] | None = "c85800000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the taste_evidence table backing inferred taste signals."""
    op.create_table(
        "taste_evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "taste_signal_id",
            sa.Integer(),
            sa.ForeignKey(
                "taste_signals.id",
                name="fk_taste_evidence_taste_signal_id_taste_signals",
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
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", name="fk_taste_evidence_event_id_events", ondelete="CASCADE"),
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
            "taste_signal_id",
            "event_id",
            name="uq_taste_evidence_signal_event",
        ),
    )
    op.create_index("ix_taste_evidence_user_id", "taste_evidence", ["user_id"])
    op.create_index("ix_taste_evidence_signal_id", "taste_evidence", ["taste_signal_id"])
    op.create_index(
        "ix_taste_evidence_user_signal",
        "taste_evidence",
        ["user_id", "signal_type", "external_key"],
    )


def downgrade() -> None:
    """Drop the taste_evidence table."""
    op.drop_index("ix_taste_evidence_user_signal", table_name="taste_evidence")
    op.drop_index("ix_taste_evidence_signal_id", table_name="taste_evidence")
    op.drop_index("ix_taste_evidence_user_id", table_name="taste_evidence")
    op.drop_table("taste_evidence")
