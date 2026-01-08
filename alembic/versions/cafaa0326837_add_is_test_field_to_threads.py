"""add_is_test_field_to_threads

Revision ID: cafaa0326837
Revises: 90fb77c79ab2
Create Date: 2026-01-08 00:08:36.116860

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cafaa0326837"
down_revision: Union[str, Sequence[str], None] = "90fb77c79ab2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_test", sa.Boolean(), nullable=False, server_default="false")
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("threads", schema=None) as batch_op:
        batch_op.drop_column("is_test")
