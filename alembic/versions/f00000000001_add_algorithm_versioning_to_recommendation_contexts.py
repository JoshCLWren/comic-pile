"""Add algorithm versioning fields to recommendation_contexts (Phase 9 #1767).

Revision ID: f00000000001
Revises: f616f65e0f1f
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f00000000001"
down_revision: str | Sequence[str] | None = "f616f65e0f1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "recommendation_contexts",
        sa.Column("algorithm_version", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "recommendation_contexts",
        sa.Column("control_mode", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("recommendation_contexts", "control_mode")
    op.drop_column("recommendation_contexts", "algorithm_version")
