"""Restore deferred status on identity check constraints (issue #5378).

Revision ID: i5378deferred01
Revises: c44050000002
Create Date: 2026-11-18 00:00:00.000000

Production is stamped at the head revision but its live
``ck_issue_external_identity_status`` constraint does not include the
``deferred`` value that c85700000001 added to the canonical schema. The
identity-inbox Defer handler writes ``status='deferred'`` and therefore fails
with a check-constraint violation (SQLSTATE 23514), surfaced as HTTP 500.

This migration is deliberately idempotent so it repairs a stamped-but-stale
database without assuming whether c85700000001 actually ran. It only widens
the status allow-list; it does not touch data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "i5378deferred01"
down_revision: str | Sequence[str] | None = "c44050000002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED = "'unresolved', 'candidate', 'confirmed', 'rejected', 'deferred'"


def upgrade() -> None:
    """Allow 'deferred' on both external-identity status constraints."""
    op.execute(
        "ALTER TABLE issue_external_identity_mappings DROP CONSTRAINT IF EXISTS "
        "ck_issue_external_identity_status"
    )
    op.execute(
        "ALTER TABLE issue_external_identity_mappings ADD CONSTRAINT "
        f"ck_issue_external_identity_status CHECK (status IN ({_ALLOWED}))"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings DROP CONSTRAINT IF EXISTS "
        "ck_thread_external_series_status"
    )
    op.execute(
        "ALTER TABLE thread_external_series_mappings ADD CONSTRAINT "
        f"ck_thread_external_series_status CHECK (status IN ({_ALLOWED}))"
    )


def downgrade() -> None:
    """No-op: the parent revision already allows 'deferred'.

    This repair exists because a deployed database can be stamped at the parent
    revision while its live constraint is older than c85700000001, which added
    'deferred' to both tables. The parent's canonical schema therefore already
    includes 'deferred'. Removing it here would both reject legitimately
    deferred rows and reintroduce the stale constraint this repair fixes, so
    downgrading restores nothing.
    """
