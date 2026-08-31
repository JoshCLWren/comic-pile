"""add skipped_thread_ids to sessions

Revision ID: 37a821bf4182
Revises: d3b4e6f8a0c2
Create Date: 2026-08-31 11:41:24.838652

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '37a821bf4182'
down_revision: Union[str, Sequence[str], None] = 'd3b4e6f8a0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('skipped_thread_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_column('skipped_thread_ids')
