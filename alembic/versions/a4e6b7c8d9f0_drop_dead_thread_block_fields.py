"""Drop dead thread block JSON fields.

Revision ID: a4e6b7c8d9f0
Revises: 64026791e5bf
Create Date: 2026-04-03 17:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4e6b7c8d9f0"
down_revision: str | Sequence[str] | None = "64026791e5bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("threads") as batch_op:
        batch_op.drop_column("blocked_by_thread_ids")
        batch_op.drop_column("blocked_by_issue_ids")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("threads") as batch_op:
        batch_op.add_column(sa.Column("blocked_by_issue_ids", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("blocked_by_thread_ids", sa.JSON(), nullable=True))
