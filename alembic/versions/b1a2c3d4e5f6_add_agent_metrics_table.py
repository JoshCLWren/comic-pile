"""add_agent_metrics_table

Revision ID: b1a2c3d4e5f6
Revises: cafaa0326837
Create Date: 2026-01-09 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1a2c3d4e5f6"
down_revision: str | Sequence[str] | None = "cafaa0326837"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("error_type", sa.String(length=255), nullable=True),
        sa.Column("api_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_agent_metrics_task_id"), "agent_metrics", ["task_id"], unique=False)
    op.create_index(op.f("ix_agent_metrics_status"), "agent_metrics", ["status"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_agent_metrics_status"), table_name="agent_metrics")
    op.drop_index(op.f("ix_agent_metrics_task_id"), table_name="agent_metrics")
    op.drop_table("agent_metrics")
