"""Add last_rating to issues (#4204).

Revision ID: r42040000001
Revises: c30740000001
Create Date: 2026-10-26 00:00:00.000000

A Thread issue row must be able to show the score the reader gave that exact
issue after a reload. ``threads.last_rating`` holds the most recent score for
the whole series, so it cannot identify a single row's saved rating; the score
is therefore stored on the issue itself.

Existing ratings live in ``events`` (``type = 'rate'`` with ``issue_id`` set),
so the column is backfilled from each issue's most recent rate event before the
row-level label can be read. Issues that were never rated stay NULL.

This revision continues the repository's single head at ``c30740000001``. It
must never point at an interior revision: a revision with an already-existing
child forks the migration graph, leaves two Alembic heads, and makes
``alembic upgrade head`` fail on deployment.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r42040000001"
down_revision: str | Sequence[str] | None = "c30740000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the per-issue saved rating and backfill it from rate events."""
    op.add_column("issues", sa.Column("last_rating", sa.Float(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE issues AS i SET last_rating = latest.rating "
            "FROM ("
            "  SELECT DISTINCT ON (issue_id) issue_id, rating"
            "  FROM events"
            "  WHERE type = 'rate' AND issue_id IS NOT NULL AND rating IS NOT NULL"
            "  ORDER BY issue_id, id DESC"
            ") AS latest "
            "WHERE i.id = latest.issue_id"
        )
    )


def downgrade() -> None:
    """Drop the per-issue saved rating."""
    op.drop_column("issues", "last_rating")
