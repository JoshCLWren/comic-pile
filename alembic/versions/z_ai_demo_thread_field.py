"""Add is_demo_thread field to Thread model

Revision ID: z_ai_demo_thread_field
Revises: cafaa0326837
Create Date: 2026-10-03 17:56:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'z_ai_demo_thread_field'
down_revision = 'cafaa0326837'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add the is_demo_thread column to threads table
    op.add_column('threads', sa.Column('is_demo_thread', sa.Boolean(), nullable=False, server_default='False'))


def downgrade() -> None:
    # Remove the is_demo_thread column
    op.drop_column('threads', 'is_demo_thread')