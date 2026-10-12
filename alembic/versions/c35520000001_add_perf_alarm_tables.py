"""Add durable performance-alarm counter and incident tables.

Revision ID: c35520000001
Revises: n7c4a1000001
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c35520000001"
down_revision: str | Sequence[str] | None = "n7c4a1000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create perf_alarm_counters and perf_alarm_incidents."""
    op.create_table(
        "perf_alarm_counters",
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("utc_day", sa.Date(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("fingerprint", "utc_day"),
    )
    op.create_table(
        "perf_alarm_incidents",
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("open_issue_number", sa.Integer(), nullable=True),
        sa.Column("last_closed_issue_number", sa.Integer(), nullable=True),
        sa.Column("last_comment_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filing_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("fingerprint"),
    )


def downgrade() -> None:
    """Drop the performance-alarm durable state tables."""
    op.drop_table("perf_alarm_incidents")
    op.drop_table("perf_alarm_counters")
