"""Merge tag exclusions branch.

Revision ID: 94d0bfc9df01
Revises: c36630000001, x3033_user_pref_excluded_tags
Create Date: 2026-10-15 20:30:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "94d0bfc9df01"
down_revision: str | Sequence[str] | None = ("c36630000001", "x3033_user_pref_excluded_tags")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration - no schema changes."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes."""
    pass
