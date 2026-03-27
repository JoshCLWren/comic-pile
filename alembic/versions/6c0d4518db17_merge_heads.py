"""merge heads

Revision ID: 6c0d4518db17
Revises: 1774529912254743360, 9b0f05146514
Create Date: 2026-03-27 10:04:44.934254

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6c0d4518db17'
down_revision: Union[str, Sequence[str], None] = ('1774529912254743360', '9b0f05146514')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
