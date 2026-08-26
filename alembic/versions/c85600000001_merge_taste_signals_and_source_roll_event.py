"""Merge branch for taste-signals table, focusing on c85500000001.

Revises: c85500000001
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85600000001"
down_revision: str | Sequence[str] | None = "c85500000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op merge point: c85500000001 now converges toward c85600000002."""
    pass


def downgrade() -> None:
    """No-op downgrade for a merge point."""
    pass