"""add task_type session_id and session_start_time to tasks

Revision ID: 2ec78b5b393a
Revises: 2d0280a50589
Create Date: 2026-01-04 09:46:25.488416

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2ec78b5b393a"
down_revision: str | Sequence[str] | None = "2d0280a50589"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tasks",
        sa.Column("task_type", sa.String(length=50), nullable=False, server_default="feature"),
    )
    op.add_column("tasks", sa.Column("session_id", sa.String(length=50), nullable=True))
    op.add_column(
        "tasks", sa.Column("session_start_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(op.f("ix_tasks_session_id"), "tasks", ["session_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tasks_session_id"), table_name="tasks")
    op.drop_column("tasks", "session_start_time")
    op.drop_column("tasks", "session_id")
    op.drop_column("tasks", "task_type")
