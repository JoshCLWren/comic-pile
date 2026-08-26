"""Merge session timezone, bandwidth updated_at, and recommendation contexts heads.

Resolves the branch that produced `c85500000002_add_recommendation_contexts`
together with `1690_session_timezone`, `c85700000001_add_deferred_status`,
and `c85900000001_add_session_bandwidth_updated_at` so the migration history
has a single linear head.

Revision ID: 05f8245be921_merge_session_timezone_bandwidth
Revises: ("1690_session_timezone", "c85700000001", "c85900000001", "c85500000002")
Create Date: 2026-08-26

"""

from collections.abc import Sequence
from alembic import op

revision: str = "05f8245be921_merge_session_timezone_bandwidth"
down_revision: str | Sequence[str] | None = "1690_session_timezone", "c85700000001", "c85900000001", "c85500000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no schema changes needed."""
    pass
