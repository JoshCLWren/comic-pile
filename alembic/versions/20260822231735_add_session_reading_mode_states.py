"""Add ephemeral reading-mode state columns to sessions."""

from alembic import op
import sqlalchemy as sa

revision = '20260822231735'
down_revision = 'caf0b46811eb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('bandwidth', sa.String(length=32), nullable=True))
    op.add_column('sessions', sa.Column('intent', sa.String(length=32), nullable=True))
    op.add_column('sessions', sa.Column('mode_source', sa.String(length=32), nullable=True, server_default='manual'))
    op.create_index(op.f('ix_session_reading_mode'), 'sessions', ['bandwidth', 'intent', 'mode_source'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_session_reading_mode'), table_name='sessions')
    op.drop_column('sessions', 'mode_source')
    op.drop_column('sessions', 'intent')
    op.drop_column('sessions', 'bandwidth')
