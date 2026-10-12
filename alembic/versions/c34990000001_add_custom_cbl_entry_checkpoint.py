"""Add checkpoint flag to custom CBL entries.

Revision ID: c34990000001
Revises: c35520000001
Create Date: 2026-10-12

Narrow extension of custom CBL authoring (#2553 / #3499): a CBL entry may
mark a crossover checkpoint that Reading Plans copy onto ``is_checkpoint``
at apply time. Roll still uses the existing checkpoint ContinuityRule
path (block the next node in the same lane). Default false preserves
existing lists.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c34990000001"
down_revision: str | Sequence[str] | None = "c35520000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the optional custom-CBL checkpoint flag."""
    op.add_column(
        "custom_cbl_entries",
        sa.Column(
            "is_checkpoint",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Remove the custom-CBL checkpoint flag."""
    op.drop_column("custom_cbl_entries", "is_checkpoint")
