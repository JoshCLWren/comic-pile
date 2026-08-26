"""Merge session timezone and bandwidth updated_at heads.

Revision ID: merge_session_timezone_bandwidth
Revises: ('1690_session_timezone', 'c85900000001')
Create Date: 2026-08-26

"""

from collections.abc import Sequence
from alembic import op

revision: str = "merge_session_timezone_bandwidth"
down_revision: str | Sequence[str] | None = ("1690_session_timezone", "c85900000001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass