"""merge all migration heads

Revision ID: 5c2bb704d311
Revises: cc1b32cfbcae, d1388e60c8f5
Create Date: 2026-01-04 09:17:01.344672

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c2bb704d311'
down_revision: Union[str, Sequence[str], None] = ('cc1b32cfbcae', 'd1388e60c8f5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
