from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1774529912254743360'
down_revision = 'f8a3b2c1d4e5'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('threads', sa.Column('touch_friendly', sa.Boolean(), nullable=False, server_default='False'))

def downgrade():
    op.drop_column('threads', 'touch_friendly')
