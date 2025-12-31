"""Add blocked fields and last heartbeat to tasks.

Revision ID: caf0b46811eb
Revises: e5f7c1ee4548
Create Date: 2025-12-31 09:30:04.930978

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "caf0b46811eb"
down_revision: str | Sequence[str] | None = "e5f7c1ee4548"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("blocked_by", sa.String(length=50), nullable=True))
    op.add_column("tasks", sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "last_heartbeat")
    op.drop_column("tasks", "blocked_by")
    op.drop_column("tasks", "blocked_reason")
