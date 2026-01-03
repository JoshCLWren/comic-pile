"""merge heads

Revision ID: 7eb7bf28b8f3
Revises: 13f7ed263206, add_settings_table
Create Date: 2026-01-02 19:18:47.256661

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '7eb7bf28b8f3'
down_revision: str | Sequence[str] | None = ('13f7ed263206', 'add_settings_table')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
