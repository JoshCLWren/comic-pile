"""Add index on collections.user_id

Revision ID: 9f67dfb81e8b
Revises: 9b0f05146514
Create Date: 2026-03-26 01:34:02.802205

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f67dfb81e8b"
down_revision: Union[str, Sequence[str], None] = "9b0f05146514"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_collections_user_id", "collections", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_collections_user_id", table_name="collections")
