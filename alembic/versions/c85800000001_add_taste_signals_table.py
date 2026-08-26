"""Add the taste_signals table for the Taste Bank inference model.

Revision ID: c85800000001
Revises: c85400000001
Create Date: 2026-08-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import ForeignKey

from alembic import op

revision: str = "c85800000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the taste_signals table."""
    op.create_table(
        "taste_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            ForeignKey("users.id", ondelete="CASCADE", name="fk_taste_signal_user_id_users"),
            nullable=False,
        ),
        sa.Column(
            "signal_type",
            sa.String(50),
            nullable=False,
        ),
        sa.Column(
            "external_key",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sa.String(200),
            nullable=False,
        ),
        sa.Column(
            "affinity_estimate",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "evidence_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "distinct_thread_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "user_verdict",
            sa.String(20),
            nullable=True,
        ),
        sa.Column(
            "first_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "signal_type",
            "external_key",
            name="uq_taste_signal_user_type_key",
        ),
    )
    op.create_index(
        "ix_taste_signal_user_id",
        "taste_signals",
        ["user_id"],
    )
    op.create_index(
        "ix_taste_signal_type_key",
        "taste_signals",
        ["signal_type", "external_key"],
    )


def downgrade() -> None:
    """Drop the taste_signals table."""
    op.drop_index("ix_taste_signal_type_key", table_name="taste_signals")
    op.drop_index("ix_taste_signal_user_id", table_name="taste_signals")
    op.drop_table("taste_signals")