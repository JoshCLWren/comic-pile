"""Merge manual creator credits with reading-plan uniqueness.

Revision ID: n6e300000001
Revises: l1a2b3c4d5e6, m5d200000001
Create Date: 2026-10-07 18:15:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "n6e300000001"
down_revision: str | Sequence[str] | None = ("l1a2b3c4d5e6", "m5d200000001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge concurrent migration heads."""
    pass


def downgrade() -> None:
    """Split the merged migration heads."""
    pass
