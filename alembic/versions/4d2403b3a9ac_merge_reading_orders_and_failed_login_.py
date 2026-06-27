"""Merge reading_orders and failed_login_attempts heads

Revision ID: 4d2403b3a9ac
Revises: 041f865a9717, a7b8c9d0e1f2
Create Date: 2026-06-26 23:32:44.929454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d2403b3a9ac'
down_revision: Union[str, Sequence[str], None] = ('041f865a9717', 'a7b8c9d0e1f2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
