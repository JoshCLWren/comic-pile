"""Add Roll bandwidth weighting columns.

Revision ID: c85900000001
Revises: c85400000001
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c85900000001"
down_revision: str | Sequence[str] | None = "c85400000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add thread effort estimates and roll weighting evidence."""
    op.add_column("threads", sa.Column("estimated_minutes", sa.Float(), nullable=True))
    op.add_column("events", sa.Column("bandwidth_weighting_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Remove the Roll bandwidth weighting columns."""
    op.drop_column("events", "bandwidth_weighting_json")
    op.drop_column("threads", "estimated_minutes")
