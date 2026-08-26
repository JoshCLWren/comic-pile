"""merge taste bank and source_roll_event_id

Revision ID: 7451dbf4e9ab
Revises: c85700000001, d4e5f6a7b8c9
Create Date: 2026-08-26 07:17:21.915459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7451dbf4e9ab'
down_revision: Union[str, Sequence[str], None] = ('c85700000001', 'd4e5f6a7b8c9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
