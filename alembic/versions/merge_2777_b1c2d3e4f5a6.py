"""Merge password reset and performance metrics heads

Revision ID: a1b2c3d4e5f6
Revises: 2777_password_reset, b1c2d3e4f5a6
Create Date: 2026-09-21 00:00:00.000000
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = ("2777_password_reset", "b1c2d3e4f5a6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge heads - no schema changes needed."""
    pass


def downgrade() -> None:
    """Downgrade - no schema changes needed."""
    pass
