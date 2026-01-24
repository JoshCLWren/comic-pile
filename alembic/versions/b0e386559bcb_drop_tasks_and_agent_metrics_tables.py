"""drop_tasks_and_agent_metrics_tables

Revision ID: b0e386559bcb
Revises: dd6f892e4e04
Create Date: 2026-01-24 13:02:20.342123

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b0e386559bcb"
down_revision: str | Sequence[str] | None = "dd6f892e4e04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop tasks and agent_metrics tables (agent orchestration removal)."""
    # Drop tables in order (no foreign key dependencies)
    op.drop_table("tasks")
    op.drop_table("agent_metrics")


def downgrade() -> None:
    """Recreate tasks and agent_metrics tables."""
    # Recreate agent_metrics table
    op.create_table(
        "agent_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_metrics_session_id", "agent_metrics", ["session_id"])
    op.create_index("ix_agent_metrics_agent_name", "agent_metrics", ["agent_name"])

    # Recreate tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("priority", sa.String(), nullable=False),
        sa.Column("assigned_agent", sa.String(), nullable=True),
        sa.Column("worktree", sa.String(), nullable=True),
        sa.Column("status_notes", sa.Text(), nullable=True),
        sa.Column("blocked_reason", sa.String(), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("task_type", sa.String(), nullable=True),
        sa.Column("session_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_assigned_agent", "tasks", ["assigned_agent"])
    op.create_index("ix_tasks_session_id", "tasks", ["session_id"])
