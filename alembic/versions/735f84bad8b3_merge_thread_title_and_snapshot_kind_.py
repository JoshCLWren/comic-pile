"""Merge thread_title and snapshot_kind heads

Revision ID: 735f84bad8b3
Revises: 3265_add_thread_title, f2a3b4c5d6e7
Create Date: 2026-10-11 21:39:35.616811

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '735f84bad8b3'
down_revision: Union[str, Sequence[str], None] = ('3265_add_thread_title', 'f2a3b4c5d6e7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
