"""Add instructions to tasks.

Revision ID: 55066689bcf4
Revises: ec7d2cfc55f0
Create Date: 2025-12-31 10:00:32.726518

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55066689bcf4"
down_revision: str | Sequence[str] | None = "ec7d2cfc55f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tasks", "instructions")
