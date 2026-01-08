"""Add notes field to threads table.

Revision ID: e61b6cf6d89a
Revises: f8a3b2c1d4e5
Create Date: 2026-01-05 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e61b6cf6d89a"
down_revision: str | Sequence[str] | None = "f8a3b2c1d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("threads", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "notes")
