"""Merge heads.

Revision ID: 45d45743a15d
Revises: 13f7ed263206, add_settings_table
Create Date: 2026-01-02 07:46:35.021354
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "45d45743a15d"
down_revision: Sequence[str] | None = ("13f7ed263206", "add_settings_table")
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
