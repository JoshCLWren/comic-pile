"""Add deferred status to external identity check constraints.

Revision ID: c85000000002
Revises: c85000000001
Create Date: 2026-08-17 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c85000000002"
down_revision: str | Sequence[str] | None = "c85000000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'deferred' to the allowed status check constraints."""
    op.execute(
        "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS "
        "ck_issue_external_identity_status"
    )
    op.execute(
        "ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT "
        "ck_issue_external_identity_status "
        "CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected', 'deferred'))"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings DROP CONSTRAINT IF EXISTS "
        "ck_thread_external_series_status"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings ADD CONSTRAINT "
        "ck_thread_external_series_status "
        "CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected', 'deferred'))"
    )


def downgrade() -> None:
    """Remove 'deferred' from the allowed status check constraints."""
    op.execute(
        "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS "
        "ck_issue_external_identity_status"
    )
    op.execute(
        "ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT "
        "ck_issue_external_identity_status "
        "CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected'))"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings DROP CONSTRAINT IF EXISTS "
        "ck_thread_external_series_status"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings ADD CONSTRAINT "
        "ck_thread_external_series_status "
        "CHECK (status IN ('unresolved', 'candidate', 'confirmed', 'rejected'))"
    )
