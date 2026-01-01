"""Add last_review_at to threads.

Revision ID: f8a3b2c1d4e5
Revises: caf0b46811eb
Create Date: 2025-12-31 16:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f8a3b2c1d4e5"
down_revision: str | Sequence[str] | None = "caf0b46811eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("threads", sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("threads", "last_review_at")
