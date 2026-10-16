"""Enforce thread-frontier ownership at the database boundary (#3225).

Revision ID: p322500000001
Revises: c36630000001
Create Date: 2026-10-16 00:00:00.000000

Adds ``uq_issues_thread_id_id`` on ``issues(thread_id, id)`` (redundant with
the primary key by design — a foreign key must reference an explicit unique
constraint) and ``fk_threads_frontier_same_thread`` from
``threads(id, next_unread_issue_id)`` to ``issues(thread_id, id)`` so the
database itself rejects a ``next_unread_issue_id`` pointing at another
thread's issue — even one owned by the same reader.

The constraint is ``DEFERRABLE INITIALLY DEFERRED`` so same-transaction
frontier recomputation (move the pointer, then delete the old issue, as
``delete_issue`` does) commits atomically. ``NULL`` frontiers pass.
Cross-user edges (dependency endpoints, plan membership, session pending
pointers, tag assignments) stay application-enforced through
``app/services/ownership_guard.py``: ``issues`` and ``dependencies`` carry
no ``user_id`` (duplicating it would fork the single ``threads.user_id``
authority), tag targets are polymorphic with no single FK target, and shared
catalog links must never authorize access to another reader's rows.

If this migration fails on existing frontier mismatches, do NOT work around
it here: run ``python scripts/check_ownership_consistency.py`` to audit, and
let the follow-up reconciliation own any production repair. Existing
violations fail the migration — they are never deleted or silently remapped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "p322500000001"
down_revision: str | Sequence[str] | None = "c36630000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the frontier same-thread uniqueness and foreign key.

    Args:
        None.

    Returns:
        None.

    Raises:
        RuntimeError: When existing threads point their frontier outside
            their own thread. Reports the count only — no titles, notes,
            or other private payload content.
    """
    bind = op.get_bind()
    mismatch_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM threads t "
            "LEFT JOIN issues i ON i.id = t.next_unread_issue_id "
            "AND i.thread_id = t.id "
            "WHERE t.next_unread_issue_id IS NOT NULL AND i.id IS NULL"
        )
    ).scalar()
    if mismatch_count:
        raise RuntimeError(
            f"Refusing to add fk_threads_frontier_same_thread with "
            f"{mismatch_count} frontier violation(s). Run "
            f"python scripts/check_ownership_consistency.py to audit; "
            f"existing violations must be reconciled, never auto-repaired."
        )
    op.create_unique_constraint(
        "uq_issues_thread_id_id",
        "issues",
        ["thread_id", "id"],
    )
    op.create_foreign_key(
        "fk_threads_frontier_same_thread",
        "threads",
        "issues",
        ["id", "next_unread_issue_id"],
        ["thread_id", "id"],
        ondelete="NO ACTION",
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    """Drop the frontier same-thread foreign key and uniqueness.

    Args:
        None.

    Returns:
        None.
    """
    op.drop_constraint(
        "fk_threads_frontier_same_thread",
        "threads",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_issues_thread_id_id",
        "issues",
        type_="unique",
    )
