"""Drop the retired Reviews persistence.

Revision ID: 7f41d0a9c2e1
Revises: d3a1c2b4e5f6
Create Date: 2026-08-05 08:55:00.000000

The Reviews product surface was removed before this migration. Production data
must be verified as no longer needed before applying this irreversible cleanup.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f41d0a9c2e1"
down_revision: str | Sequence[str] | None = "d3a1c2b4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove orphaned Reviews storage and thread metadata."""
    op.drop_table("reviews")

    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_column("review_url")
        batch_op.drop_column("last_review_at")


def downgrade() -> None:
    """Refuse to recreate destructively removed review data."""
    raise RuntimeError(
        "The retired Reviews data cannot be restored by downgrade; restore a database backup instead."
    )
