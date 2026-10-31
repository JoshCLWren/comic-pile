"""Give activity events independent user ownership without erasing session history.

Revision ID: c44050000001
Revises: c42550000001

Every recoverable historical event receives its original owner. Preserve legacy
unattributed delete events with NULL ownership instead of guessing a user. Keep session and snapshot tables for their
current consumers, but make deleting a session NULL its event link instead of
deleting the events. The trigger lets existing Python and Rust session-based
writers continue working without a coordinated API cutover.
"""

from alembic import op
import sqlalchemy as sa

revision = "c44050000001"
down_revision = "c42550000001"
branch_labels = None
depends_on = None


# Quarantine rows whose surviving references disagree with the recorded
# owner. New activity is rejected by the trigger; historical rows are kept
# intact but excluded from every owner-scoped projection.
OWNER_AGREEMENT_GUARD = """
        UPDATE events e SET user_id = NULL
        WHERE e.user_id IS NOT NULL AND (
            EXISTS (
                SELECT 1 FROM sessions s
                WHERE s.id = e.session_id AND s.user_id <> e.user_id
            )
            OR EXISTS (
                SELECT 1 FROM threads t
                WHERE t.id = e.thread_id AND t.user_id <> e.user_id
            )
            OR EXISTS (
                SELECT 1 FROM issues i JOIN threads t ON t.id = i.thread_id
                WHERE i.id = e.issue_id AND t.user_id <> e.user_id
            )
            OR EXISTS (
                SELECT 1 FROM threads t
                WHERE t.id = e.selected_thread_id AND t.user_id <> e.user_id
            )
            OR EXISTS (
                SELECT 1 FROM events source
                WHERE source.id = e.source_roll_event_id
                  AND source.user_id IS NOT NULL
                  AND source.user_id <> e.user_id
            )
        )
"""


EVENT_USER_INDEX = "ix_event_user_timestamp_id"


def _event_user_index_is_valid() -> bool:
    """Return whether the owner-scoped activity index already exists and is usable.

    Returns:
        True when the index exists in the current schema with ``indisvalid``.
    """
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT i.indisvalid
                FROM pg_index i
                JOIN pg_class c ON c.oid = i.indexrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = :name AND n.nspname = current_schema()
                """
            ),
            {"name": EVENT_USER_INDEX},
        )
        .first()
    )
    return row is not None and bool(row[0])


def _create_event_user_index() -> None:
    """Build the owner-scoped activity index without blocking Roll writes.

    ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction, and a
    cancelled build can leave an invalid index behind. Drop that residue and
    rebuild so a retried migration converges on a usable index.
    """
    if _event_user_index_is_valid():
        return
    op.drop_index(
        EVENT_USER_INDEX,
        table_name="events",
        if_exists=True,
        postgresql_concurrently=True,
    )
    op.create_index(
        EVENT_USER_INDEX,
        "events",
        ["user_id", sa.text("timestamp DESC"), sa.text("id DESC")],
        postgresql_concurrently=True,
    )


def upgrade() -> None:
    op.add_column("events", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_events_user_id_users", "events", "users", ["user_id"], ["id"],
        ondelete="CASCADE",
    )

    # The session FK is the strongest historical ownership evidence.
    op.execute("""
        UPDATE events e SET user_id = s.user_id
        FROM sessions s WHERE e.session_id = s.id
    """)
    # The nullable session_id existed before this migration. Preserve any
    # detached activity with an independently verifiable owned reference.
    op.execute("""
        UPDATE events e SET user_id = t.user_id
        FROM threads t WHERE e.user_id IS NULL AND e.thread_id = t.id
    """)
    op.execute("""
        UPDATE events e SET user_id = t.user_id
        FROM issues i JOIN threads t ON t.id = i.thread_id
        WHERE e.user_id IS NULL AND e.issue_id = i.id
    """)
    op.execute("""
        UPDATE events e SET user_id = t.user_id
        FROM threads t
        WHERE e.user_id IS NULL AND e.selected_thread_id = t.id
    """)
    # Greedy attribution above trusts the strongest surviving reference. If a
    # corrupt historical row carries references owned by different readers,
    # keep it unattributed instead of silently assigning one of them; this
    # matches the fail-closed agreement check the trigger applies to new rows.
    # The production read-only audit (2026-10-30) found no such conflicts, so
    # this is a guard against malformed data, not a reclassification of
    # reviewed records.
    # First pass: quarantine historical rows whose own references disagree.
    op.execute(OWNER_AGREEMENT_GUARD)
    # A dependent event may inherit its source roll's owner, but only after
    # the guard has quarantined sources with conflicting references.
    op.execute("""
        UPDATE events e SET user_id = source.user_id
        FROM events source
        WHERE e.user_id IS NULL AND e.source_roll_event_id = source.id
          AND source.user_id IS NOT NULL
    """)
    # Second pass: a source-inherited owner must still agree with the
    # event's own surviving references.
    op.execute(OWNER_AGREEMENT_GUARD)
    # Some historical thread-deletion events have had every ownership reference
    # removed. Production currently has 192 such records (2026-10-30).
    # Keep these rows intact with NULL owner rather than inventing a user or
    # blocking deployment. Owner-scoped history never returns them. All *new*
    # activity, including sessionless activity, requires a verified user_id
    # through the INSERT trigger below.

    # Session-independent history is not allowed to disappear in a session
    # cleanup. User deletion still cascades via the new FK.
    op.drop_constraint("events_session_id_fkey", "events", type_="foreignkey")
    op.create_foreign_key(
        "events_session_id_fkey", "events", "sessions", ["session_id"], ["id"],
        ondelete="SET NULL",
    )
    # Database-side compatibility for existing session-based and thread/issue
    # based writers; sessionless reference-free deletes now pass explicit owner.
    # The authenticated owner must be supplied explicitly for new sessionless
    # activity; a conflicting supplied owner never overrides the session owner.
    op.execute("""
        CREATE FUNCTION assign_event_owner() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE inferred_owner integer;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                -- Legacy writers do not yet pass user_id. Most direct Mark Read,
                -- issue, and queue events already have an owned thread/issue.
                -- Deletions with no surviving references pass user_id explicitly.
                IF NEW.session_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM sessions WHERE id = NEW.session_id;
                ELSIF NEW.thread_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM threads WHERE id = NEW.thread_id;
                ELSIF NEW.issue_id IS NOT NULL THEN
                    SELECT t.user_id INTO inferred_owner
                    FROM issues i JOIN threads t ON t.id = i.thread_id
                    WHERE i.id = NEW.issue_id;
                ELSIF NEW.selected_thread_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM threads WHERE id = NEW.selected_thread_id;
                ELSIF NEW.source_roll_event_id IS NOT NULL THEN
                    SELECT user_id INTO inferred_owner
                    FROM events WHERE id = NEW.source_roll_event_id;
                END IF;
                IF inferred_owner IS NOT NULL AND NEW.user_id IS NOT NULL
                   AND NEW.user_id <> inferred_owner THEN
                    RAISE EXCEPTION 'event owner conflicts with owning reference'
                        USING ERRCODE = '23514';
                END IF;
                NEW.user_id := COALESCE(NEW.user_id, inferred_owner);
                IF NEW.user_id IS NULL THEN
                    RAISE EXCEPTION 'event requires an owner or an owned reference'
                        USING ERRCODE = '23502';
                END IF;
            ELSE
                -- Ownership is established on insert and never inferred or
                -- reassigned later. A session-cleanup SET NULL must not
                -- attribute a preserved historical row, and a recorded owner
                -- must never move to a different reader.
                IF NEW.user_id IS DISTINCT FROM OLD.user_id THEN
                    RAISE EXCEPTION 'event ownership is immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            -- A compound event may carry several references. The first
            -- determines a missing owner, but *every* existing reference
            -- must agree with that owner to prevent cross-reader linkage.
            -- Unattributed historical rows stay outside owner projections.
            IF NEW.user_id IS NOT NULL THEN
                IF EXISTS (
                    SELECT 1 FROM sessions s
                    WHERE s.id = NEW.session_id AND s.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM threads t
                    WHERE t.id = NEW.thread_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM issues i JOIN threads t ON t.id = i.thread_id
                    WHERE i.id = NEW.issue_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM threads t
                    WHERE t.id = NEW.selected_thread_id AND t.user_id <> NEW.user_id
                ) OR EXISTS (
                    SELECT 1 FROM events source
                    WHERE source.id = NEW.source_roll_event_id
                      AND source.user_id IS NOT NULL
                      AND source.user_id <> NEW.user_id
                ) THEN
                    RAISE EXCEPTION 'event references data owned by another user'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_assign_event_owner
        BEFORE INSERT OR UPDATE OF user_id, session_id, thread_id, issue_id,
            selected_thread_id, source_roll_event_id ON events
        FOR EACH ROW EXECUTE FUNCTION assign_event_owner()
    """)
    # Build the owner-scoped activity index concurrently only after the
    # ownership trigger exists: the concurrent build commits the preceding
    # transaction, and legacy writers must already be protected during that
    # window. That commit is not stamped as a completed revision, so an
    # interruption here or earlier needs manual recovery: the committed column,
    # backfill, and trigger make a plain re-run fail before reaching the
    # restartable invalid-index rebuild inside _create_event_user_index().
    with op.get_context().autocommit_block():
        _create_event_user_index()


def downgrade() -> None:
    # Undo would restore ON DELETE CASCADE and risk deleting user history.
    raise RuntimeError("Event ownership migration preserves history and must not be reversed blindly")
