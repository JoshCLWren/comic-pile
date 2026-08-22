"""Add recommendation_contexts table for intent/Taste Bank factor recording.

Revision ID: c85300000001
Revises: c85200000001
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85300000001"
down_revision: str | Sequence[str] | None = "c85200000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create recommendation_contexts table for auditability."""
    op.create_table(
        "recommendation_contexts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("events.id", name="fk_recommendation_contexts_event_id_events", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("intent", sa.String(30), nullable=False),
        sa.Column("intent_source", sa.String(30), nullable=False),
        sa.Column("intent_confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("bandwidth", sa.String(30), nullable=True),
        sa.Column("bandwidth_source", sa.String(30), nullable=True),
        sa.Column("bandwidth_confidence", sa.Float(), nullable=True),
        sa.Column("candidate_factors", sa.JSON(), nullable=True),
        sa.Column("final_weight", sa.Float(), nullable=True),
        sa.Column("random_bypass", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balanced_neutrality", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recommendation_contexts_event_id", "recommendation_contexts", ["event_id"])
    op.create_index("ix_recommendation_contexts_created_at", "recommendation_contexts", ["created_at"])
    op.create_index("ix_recommendation_contexts_intent", "recommendation_contexts", ["intent"])


def downgrade() -> None:
    """Drop recommendation_contexts table."""
    op.drop_index("ix_recommendation_contexts_intent", table_name="recommendation_contexts")
    op.drop_index("ix_recommendation_contexts_created_at", table_name="recommendation_contexts")
    op.drop_index("ix_recommendation_contexts_event_id", table_name="recommendation_contexts")
    op.drop_table("recommendation_contexts")
