"""Merge session timezone, bandwidth updated_at, and recommendation contexts heads.

Resolves the branch that produced `c85500000002_add_recommendation_contexts`
together with `c85900000001_add_session_bandwidth_updated_at` so the migration
history has a single linear head.

`1690_session_timezone` is an ancestor of `c85500000002`, and
`c85700000001_add_deferred_status` was already merged by `05f8245be920`,
so only the two true leaf heads are listed below.

Revision ID: 05f8245be921
Revises: ("c85900000001", "c85500000002")
Create Date: 2026-08-26

"""

from collections.abc import Sequence
from alembic import op

revision: str = "05f8245be921"
down_revision: str | Sequence[str] | None = ("c85900000001", "c85500000002")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass
