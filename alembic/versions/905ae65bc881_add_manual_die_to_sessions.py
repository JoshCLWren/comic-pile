"""Add manual die to sessions.

Revision ID: 905ae65bc881
Revises: 7eb7bf28b8f3
Create Date: 2026-01-02 19:18:51.896761

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "905ae65bc881"
down_revision: str | Sequence[str] | None = "7eb7bf28b8f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("manual_die", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "manual_die")
