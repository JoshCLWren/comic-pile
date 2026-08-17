"""Add user preferences column.

Revision ID: b2c3d4e5f6a7
Revises: c85100000001
Create Date: 2026-08-17 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "c85100000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the preferences JSONB column to the users table."""
    op.add_column(
        "users",
        sa.Column("preferences", sa.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Remove the preferences column from the users table."""
    op.drop_column("users", "preferences")
