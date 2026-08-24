"""Merge c855 heads: cache schema, session bandwidth, taste signals.

Revision ID: c85500000005
Revises: c85500000001, c85500000003, c85500000004
Create Date: 2026-08-24 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85500000005"
down_revision: Sequence[str] | None = ("c85500000003", "c85500000004")
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration - no schema changes."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes."""
    pass