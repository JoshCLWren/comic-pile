"""Merge heads before dropping redundant index

Revision ID: 84d72448ea93
Revises: 4882a6a20f35, be75ffc829e2
Create Date: 2026-04-05 22:39:03.466894

"""
from collections.abc import Sequence



# revision identifiers, used by Alembic.
revision: str = '84d72448ea93'
down_revision: str | Sequence[str] | None = ('4882a6a20f35', 'be75ffc829e2')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
