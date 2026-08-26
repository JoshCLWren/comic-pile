"""Merge Alembic branch heads c85600000001 and c85800000001.

Both revisions diverged from d4e5f6a7b8c9 on base main, so this
merge-point keeps the migration graph linear without dropping or
replaying any schema changes.

Revision ID: c85600000002
Revises: c85600000001, c85800000001
Create Date: 2026-08-25 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85600000002"
down_revision: str | Sequence[str] | None = ("c85600000001", "c85800000001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge c85600000001 and c85800000001 migration heads."""


def downgrade() -> None:
    """No-op downgrade for a merge point."""