"""Enforce reader ownership consistency at graph and library write boundaries (#3225).

Revision ID: m5d400000001
Revises: c36420000001
Create Date: 2026-10-14 00:00:00.000000

Adds the two PostgreSQL-level ownership triggers described in
``docs/READER_OWNERSHIP_CONSISTENCY.md``:

- ``trg_threads_frontier_ownership`` - ``threads.next_unread_issue_id`` must
  reference an issue of that exact thread, not merely an issue the reader owns.
- ``trg_sessions_pending_ownership`` - ``sessions.pending_thread_id`` must
  reference a thread owned by the session's reader.

``sessions.pending_issue_id`` is deliberately not constrained to the pending
thread: roll advances ``pending_thread_id`` on every selection while
``pending_issue_id`` keeps the reader's last explicitly pinned issue, so a
stale cross-thread pin is normal reader state.

Why triggers rather than composite foreign keys: the frontier foreign key would
have to be ``ON DELETE SET NULL (next_unread_issue_id)`` on PostgreSQL 16, and
it would make every existing ``Thread``/``Issue`` relationship join ambiguous
for SQLAlchemy; the session column is nullable and cleared as the roll
advances, so a composite foreign key adds nothing over the existing
single-column one. The existing single-column foreign keys and their
``ON DELETE SET NULL`` behaviour are unchanged, so every existing delete path
keeps working.

Nothing here deletes, remaps, or auto-repairs a row. Existing violations are
reported read-only by ``scripts/audit_reader_ownership_violations.py`` and by
the preflight checks in ``alembic/preflight/m5d400000001.json``, which run
before this migration and fail the deploy while any invalid row remains.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "m5d400000001"
down_revision: str | Sequence[str] | None = "c36420000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

THREAD_FRONTIER_TRIGGER_STATEMENTS: tuple[str, ...] = (
    """
CREATE OR REPLACE FUNCTION cp_enforce_thread_frontier_ownership()
RETURNS trigger
LANGUAGE plpgsql
AS $cp$
BEGIN
    IF NEW.next_unread_issue_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM issues i
        WHERE i.id = NEW.next_unread_issue_id
          AND i.thread_id = NEW.id
    ) THEN
        RAISE EXCEPTION
            'threads.next_unread_issue_id must reference an issue of the same thread'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$cp$;
""",
    "DROP TRIGGER IF EXISTS trg_threads_frontier_ownership ON threads;",
    """
CREATE TRIGGER trg_threads_frontier_ownership
BEFORE INSERT OR UPDATE ON threads
FOR EACH ROW
EXECUTE FUNCTION cp_enforce_thread_frontier_ownership();
""",
)

SESSION_PENDING_TRIGGER_STATEMENTS: tuple[str, ...] = (
    """
CREATE OR REPLACE FUNCTION cp_enforce_session_pending_ownership()
RETURNS trigger
LANGUAGE plpgsql
AS $cp$
BEGIN
    IF NEW.pending_thread_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM threads t
        WHERE t.id = NEW.pending_thread_id
          AND t.user_id = NEW.user_id
    ) THEN
        RAISE EXCEPTION
            'sessions.pending_thread_id must reference a thread owned by the session reader'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$cp$;
""",
    "DROP TRIGGER IF EXISTS trg_sessions_pending_ownership ON sessions;",
    """
CREATE TRIGGER trg_sessions_pending_ownership
BEFORE INSERT OR UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION cp_enforce_session_pending_ownership();
""",
)


def upgrade() -> None:
    """Install the reader-ownership triggers.

    Args:
        None.

    Returns:
        None.
    """
    for statement in THREAD_FRONTIER_TRIGGER_STATEMENTS:
        op.execute(statement)
    for statement in SESSION_PENDING_TRIGGER_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Remove the reader-ownership triggers and their functions.

    Args:
        None.

    Returns:
        None.
    """
    op.execute("DROP TRIGGER IF EXISTS trg_sessions_pending_ownership ON sessions")
    op.execute("DROP FUNCTION IF EXISTS cp_enforce_session_pending_ownership()")
    op.execute("DROP TRIGGER IF EXISTS trg_threads_frontier_ownership ON threads")
    op.execute("DROP FUNCTION IF EXISTS cp_enforce_thread_frontier_ownership()")