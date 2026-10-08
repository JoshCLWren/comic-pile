"""Add thread_title to events for deleted-thread history display.

Revision ID: p7e400000001
Revises: n6e300000001
Create Date: 2026-10-08 00:00:00.000000

Events denormalize the thread title at write time so the History timeline can
name a thread after the thread row is deleted, mirroring the existing
``events.issue_number`` column for deleted issues. Without this column every
event insert fails on a migrated database, so the migration ships with the
model change (issue #3265).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p7e400000001"
down_revision: str | Sequence[str] | None = "n6e300000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    """Return the current column names for a table."""
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    """Add the nullable denormalized thread_title column to events."""
    if "thread_title" in _column_names("events"):
        return
    op.add_column("events", sa.Column("thread_title", sa.String(200), nullable=True))


def downgrade() -> None:
    """Remove the denormalized thread_title column from events."""
    if "thread_title" not in _column_names("events"):
        return
    op.drop_column("events", "thread_title")
