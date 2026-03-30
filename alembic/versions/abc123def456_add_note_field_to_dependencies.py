"""Add note field to dependencies table.

Revision ID: abc123def456
Revises:
Create Date: 2026-03-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "abc123def456"
down_revision: str | Sequence[str] | None = "e61b6cf6d89a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("dependencies", sa.Column("note", sa.String(255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("dependencies", "note")
