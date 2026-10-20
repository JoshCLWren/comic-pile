"""Add queue_position_is_manual to threads (#3638).

Revision ID: q4m500000001
Revises: c32320000001
Create Date: 2026-10-20 00:00:00.000000

The reader's explicit queue placement (move to front/back/position) is stored
separately from the numeric position so an automatic below-threshold rating
cannot silently demote a manually placed series. Existing rows start as
``false`` because none of them has a recorded manual claim.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "q4m500000001"
down_revision: str | Sequence[str] | None = "c32320000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the manual-placement flag and backfill existing rows as false."""
    op.add_column(
        "threads",
        sa.Column(
            "queue_position_is_manual",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Drop the manual-placement flag."""
    op.drop_column("threads", "queue_position_is_manual")
