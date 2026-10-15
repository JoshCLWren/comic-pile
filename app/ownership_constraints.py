"""PostgreSQL-level reader-ownership enforcement for graph/library write edges.

Issue #3225 makes reader ownership an enforced property of the write
boundaries, not an application convention. Two edges need database enforcement
that an ordinary foreign key cannot give them without changing delete
semantics:

``threads.next_unread_issue_id``
    The natural frontier must belong to *that exact thread*. A composite
    foreign key ``(next_unread_issue_id, id) -> issues(id, thread_id)`` is
    expressible on PostgreSQL 16 only as
    ``ON DELETE SET NULL (next_unread_issue_id)`` (plain ``ON DELETE SET NULL``
    would also null the not-null primary key ``threads.id``), and it makes
    every existing ``Thread``/``Issue`` relationship join ambiguous for
    SQLAlchemy. The trigger enforces exactly the same invariant while leaving
    the existing single-column ``ON DELETE SET NULL`` foreign key - and
    therefore every delete path - untouched.

``sessions.pending_thread_id``
    A pending reference must belong to the session's reader. The column is
    nullable and is cleared as the roll advances, so a composite foreign key
    adds nothing over the existing single-column one while costing the same
    delete-semantics problem.

``sessions.pending_issue_id`` is deliberately *not* constrained to the pending
thread. Roll advances ``pending_thread_id`` on every selection while
``pending_issue_id`` keeps the reader's last explicitly pinned issue, so a
stale cross-thread pin is normal reader state, not a violation. The pin is
only ever written from an issue the caller already owns.

Both triggers run ``BEFORE INSERT OR UPDATE``, so they reject invalid direct
SQL inserts and updates with ``integrity_constraint_violation``. Existing
violations are reported read-only by
``scripts/audit_reader_ownership_violations.py`` and by the preflight manifest
``alembic/preflight/m5d400000001.json``; nothing here deletes, remaps, or
auto-repairs an existing row.

Each item in the ``*_TRIGGER_STATEMENTS`` tuples is a single SQL statement so
the same text is safe for asyncpg's simple query protocol during
``Base.metadata.create_all`` and for the sync driver Alembic uses.

See ``docs/READER_OWNERSHIP_CONSISTENCY.md`` for the enforced/undeclared split.
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.schema import DDL

#: Trigger names installed on ``threads`` and ``sessions``.
THREAD_FRONTIER_TRIGGER_NAME = "trg_threads_frontier_ownership"
SESSION_PENDING_TRIGGER_NAME = "trg_sessions_pending_ownership"

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
    f"DROP TRIGGER IF EXISTS {THREAD_FRONTIER_TRIGGER_NAME} ON threads;",
    f"""
CREATE TRIGGER {THREAD_FRONTIER_TRIGGER_NAME}
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
    f"DROP TRIGGER IF EXISTS {SESSION_PENDING_TRIGGER_NAME} ON sessions;",
    f"""
CREATE TRIGGER {SESSION_PENDING_TRIGGER_NAME}
BEFORE INSERT OR UPDATE ON sessions
FOR EACH ROW
EXECUTE FUNCTION cp_enforce_session_pending_ownership();
""",
)


def install_reader_ownership_constraints() -> None:
    """Register the reader-ownership triggers with the owning tables.

    Called once from ``app/models/__init__.py`` after every model is imported so
    ``Base.metadata.create_all`` (test fixtures) installs exactly the same
    PostgreSQL enforcement the Alembic migration installs in production.

    The model imports live here instead of at module scope: ``app.models`` calls
    this function while its own package is still initializing, so a module-scope
    ``from app.models.thread import Thread`` would make any first-touch import of
    ``app.ownership_constraints`` fail with a circular-import error.

    The DDL is PostgreSQL-only: ``create_all`` against another dialect must not
    fail, and the single-column foreign keys still provide existence checks.
    """
    from app.models.reading_session import ReadingSession
    from app.models.thread import Thread

    for statement in THREAD_FRONTIER_TRIGGER_STATEMENTS:
        event.listen(
            Thread.__table__,
            "after_create",
            DDL(statement).execute_if(dialect="postgresql"),
        )
    for statement in SESSION_PENDING_TRIGGER_STATEMENTS:
        event.listen(
            ReadingSession.__table__,
            "after_create",
            DDL(statement).execute_if(dialect="postgresql"),
        )