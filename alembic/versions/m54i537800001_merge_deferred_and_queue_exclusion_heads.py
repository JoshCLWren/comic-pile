"""Merge deferred-identity repair and queue exclusion heads.

Revision ID: m54i537800001
Revises: i5378deferred01, s54350000001
Create Date: 2026-11-19 01:45:00.000000
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "m54i537800001"
down_revision: str | Sequence[str] | None = ("i5378deferred01", "s54350000001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge schema heads."""
    pass


def downgrade() -> None:
    """Unmerge schema heads."""
    pass
