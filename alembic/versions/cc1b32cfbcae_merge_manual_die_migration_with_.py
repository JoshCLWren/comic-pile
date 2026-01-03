"""Merge manual_die migration with existing heads.

Revision ID: cc1b32cfbcae
Revises: 45d45743a15d, 905ae65bc881
Create Date: 2026-01-03 00:03:33.074298
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "cc1b32cfbcae"
down_revision: Sequence[str] | None = ("45d45743a15d", "905ae65bc881")
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
