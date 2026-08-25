"""merge session bandwidth, taste signals, reading mode, reason codes, and deferred status heads

Revision ID: 05f8245be920
Revises: 3e9443eeca36, 83b5669f636c, c85500000001, c85600000001, c85700000001, f7e8d9c0b1a2
Create Date: 2026-08-24 18:35:44.265905

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '05f8245be920'
down_revision: Union[str, Sequence[str], None] = ('3e9443eeca36', '83b5669f636c', 'c85500000001', 'c85600000001', 'c85700000001', 'f7e8d9c0b1a2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass