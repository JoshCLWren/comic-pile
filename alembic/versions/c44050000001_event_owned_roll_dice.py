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
    op.execute("""
        UPDATE events e SET user_id = source.user_id
        FROM events source
        WHERE e.user_id IS NULL AND e.source_roll_event_id = source.id
          AND source.user_id IS NOT NULL
    """)
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
    op.create_index(
        "ix_event_user_timestamp_id", "events",
        ["user_id", sa.text("timestamp DESC"), sa.text("id DESC")],
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
            IF TG_OP = 'UPDATE' AND NEW.user_id <> OLD.user_id THEN
                RAISE EXCEPTION 'event ownership is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_assign_event_owner
        BEFORE INSERT OR UPDATE OF user_id, session_id ON events
        FOR EACH ROW EXECUTE FUNCTION assign_event_owner()
    """)


def downgrade() -> None:
    # Undo would restore ON DELETE CASCADE and risk deleting user history.
    raise RuntimeError("Event ownership migration preserves history and must not be reversed blindly")
