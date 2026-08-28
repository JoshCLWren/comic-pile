"""Add recommendation algorithm version and control state to Event

Revision ID: c85c00000001
Revises: 05f8245be921
Create Date: 2026-08-28 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c85c00000001"
down_revision: str | Sequence[str] | None = "05f8245be921"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "events",
        sa.Column("algorithm_version", sa.String(20), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("algorithm_control_state", sa.String(30), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("events", "algorithm_control_state")
    op.drop_column("events", "algorithm_version")
