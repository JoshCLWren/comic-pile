"""Add thread_title to Event model for historical display of deleted threads.

Revision ID: 3265_add_thread_title
Revises: n6e300000001
Create Date: 2026-10-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3265_add_thread_title"
down_revision: str | Sequence[str] | None = "n6e300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add thread_title column to events table for historical thread name display."""
    op.add_column("events", sa.Column("thread_title", sa.String(200), nullable=True))


def downgrade() -> None:
    """Remove thread_title column from events table."""
    op.drop_column("events", "thread_title")