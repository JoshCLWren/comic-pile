"""merge heads

Revision ID: d1388e60c8f5
Revises: 13f7ed263206, add_settings_table
Create Date: 2026-01-03 16:53:03.831298

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1388e60c8f5'
down_revision: Union[str, Sequence[str], None] = ('13f7ed263206', 'add_settings_table')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
