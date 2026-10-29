"""Add last_rating to issues (#4204).

Revision ID: r420400000001
Revises: c42550000001
Create Date: 2026-10-29 00:00:00.000000

A Thread keeps only ``last_rating`` for the series as a whole, so the Thread
issue rows could not show the rating saved for each individual issue after a
reload. Store the rating on the Issue row instead; undo snapshots already
capture issue preimages, so undoing a rating restores the previous issue-level
rating as well.

Existing rows start as NULL rather than being backfilled from historical rate
events: event history cannot distinguish ratings that were later undone, and a
guessed saved rating is worse than no saved rating at all.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "r420400000001"
down_revision: str | Sequence[str] | None = "c42550000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the per-issue rating column."""
    op.add_column("issues", sa.Column("last_rating", sa.Float(), nullable=True))


def downgrade() -> None:
    """Drop the per-issue rating column."""
    op.drop_column("issues", "last_rating")
