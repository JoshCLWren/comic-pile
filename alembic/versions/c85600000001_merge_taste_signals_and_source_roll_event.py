"""Merge branch for taste-signals table and source-roll-event.

Revision ID: c85600000001
Revises: c85500000001, d4e5f6a7b8c9
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85600000001"
down_revision: str | Sequence[str] | None = ("c85500000001", "d4e5f6a7b8c9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge taste-signals branch with source-roll-event branch."""
    pass


def downgrade() -> None:
    """No-op downgrade for a merge point."""
    pass