"""merge heads

Revision ID: 58c2d0ee93f3
Revises: 0e45016da0d7, f1a2b3c4d5e6
Create Date: 2026-02-23 08:13:58.820156

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58c2d0ee93f3'
down_revision: Union[str, Sequence[str], None] = ('0e45016da0d7', 'f1a2b3c4d5e6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
