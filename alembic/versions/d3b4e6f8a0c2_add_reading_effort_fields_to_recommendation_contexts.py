"""Add reading-effort estimate fields to recommendation_contexts.

Revision ID: d3b4e6f8a0c2
Revises: c2a1b0d3e4f5
Create Date: 2026-08-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b4e6f8a0c2"
down_revision: str | Sequence[str] | None = "c85500000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("recommendation_contexts", sa.Column("effort_minutes", sa.Float(), nullable=True))
    op.add_column("recommendation_contexts", sa.Column("effort_band", sa.String(length=20), nullable=True))
    op.add_column("recommendation_contexts", sa.Column("effort_source", sa.String(length=30), nullable=True))
    op.add_column("recommendation_contexts", sa.Column("effort_confidence", sa.Float(), nullable=True))
    op.add_column("recommendation_contexts", sa.Column("effort_sample_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("recommendation_contexts", "effort_sample_count")
    op.drop_column("recommendation_contexts", "effort_confidence")
    op.drop_column("recommendation_contexts", "effort_source")
    op.drop_column("recommendation_contexts", "effort_band")
    op.drop_column("recommendation_contexts", "effort_minutes")
