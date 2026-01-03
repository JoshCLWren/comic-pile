"""Merge heads.

Revision ID: d1388e60c8f5
Revises: 13f7ed263206, add_settings_table
Create Date: 2026-01-03 16:53:03.831298

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d1388e60c8f5"
down_revision: str | Sequence[str] | None = ("13f7ed263206", "add_settings_table")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
