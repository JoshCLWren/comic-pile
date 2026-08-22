"""Add Taste Bank signals table

Revision ID: 9f67dfb81e8b_add_taste_bank_signals_table
Revises: 9b0f05146514
Create Date: 2026-08-22 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f67dfb81e8b'
down_revision = '9b0f05146514'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('taste_bank_signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('signal_type', sa.String(length=50), nullable=False),
        sa.Column('verdict', sa.String(length=20), nullable=False),
        sa.Column('evidence', sa.String(length=1000), nullable=True),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'signal_type', name='uq_taste_bank_signal'),
        sa.Index('ix_taste_bank_signals_user_id', 'user_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('taste_bank_signals')