"""Migrate data from SQLite to PostgreSQL."""

import json
import os
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Event, Session, Snapshot, Thread, User

env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

sqlite_db_path = os.getenv("SQLITE_DB_PATH", "comic_pile.db")
if not os.path.isabs(sqlite_db_path):
    sqlite_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), sqlite_db_path)

sqlite_conn = sqlite3.connect(sqlite_db_path)
sqlite_conn.row_factory = sqlite3.Row

pg_url = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://comicpile:comicpile_password@localhost:5435/comicpile"
)
pg_engine = create_engine(pg_url)
pg_session = sessionmaker(bind=pg_engine)()


def migrate_users():
    """Migrate users table."""
    cursor = sqlite_conn.execute("SELECT * FROM users")
    rows = cursor.fetchall()
    for row in rows:
        user = User(
            id=row["id"],
            username=row["username"],
            created_at=row["created_at"],
        )
        pg_session.merge(user)
    pg_session.commit()
    print(f"Migrated {len(rows)} users")


def migrate_threads():
    """Migrate threads table."""
    cursor = sqlite_conn.execute("SELECT * FROM threads")
    rows = cursor.fetchall()
    for row in rows:
        is_test = row["is_test"]
        if isinstance(is_test, str):
            is_test = is_test.lower() == "true"
        elif is_test is None:
            is_test = False

        thread = Thread(
            id=row["id"],
            title=row["title"],
            format=row["format"],
            issues_remaining=row["issues_remaining"],
            queue_position=row["queue_position"],
            status=row["status"],
            last_rating=row["last_rating"] if row["last_rating"] else None,
            last_activity_at=row["last_activity_at"] if row["last_activity_at"] else None,
            review_url=row["review_url"] if row["review_url"] else None,
            last_review_at=row["last_review_at"] if row["last_review_at"] else None,
            notes=row["notes"] if row["notes"] else None,
            is_test=is_test,
            created_at=row["created_at"],
            user_id=row["user_id"],
        )
        pg_session.merge(thread)
    pg_session.commit()
    print(f"Migrated {len(rows)} threads")


def migrate_sessions():
    """Migrate sessions table."""
    cursor = sqlite_conn.execute("SELECT * FROM sessions")
    rows = cursor.fetchall()

    cursor_threads = sqlite_conn.execute("SELECT id FROM threads")
    valid_thread_ids = {row[0] for row in cursor_threads.fetchall()}

    for row in rows:
        pending_thread_id = row["pending_thread_id"] if row["pending_thread_id"] else None
        if pending_thread_id and pending_thread_id not in valid_thread_ids:
            pending_thread_id = None

        session = Session(
            id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"] if row["ended_at"] else None,
            start_die=row["start_die"],
            manual_die=row["manual_die"] if row["manual_die"] else None,
            user_id=row["user_id"],
            pending_thread_id=pending_thread_id,
            pending_thread_updated_at=row["pending_thread_updated_at"]
            if row["pending_thread_updated_at"]
            else None,
        )
        pg_session.merge(session)
    pg_session.commit()
    print(f"Migrated {len(rows)} sessions")


def migrate_events():
    """Migrate events table."""
    cursor = sqlite_conn.execute("SELECT * FROM events")
    rows = cursor.fetchall()
    for row in rows:
        event = Event(
            id=row["id"],
            type=row["type"],
            timestamp=row["timestamp"],
            die=row["die"] if row["die"] else None,
            result=row["result"] if row["result"] else None,
            selected_thread_id=row["selected_thread_id"] if row["selected_thread_id"] else None,
            selection_method=row["selection_method"] if row["selection_method"] else None,
            rating=row["rating"] if row["rating"] else None,
            issues_read=row["issues_read"] if row["issues_read"] else None,
            queue_move=row["queue_move"] if row["queue_move"] else None,
            die_after=row["die_after"] if row["die_after"] else None,
            session_id=row["session_id"],
            thread_id=row["thread_id"],
        )
        pg_session.merge(event)
    pg_session.commit()
    print(f"Migrated {len(rows)} events")


def migrate_snapshots():
    """Migrate snapshots table."""
    cursor = sqlite_conn.execute("SELECT * FROM snapshots")
    rows = cursor.fetchall()

    cursor_events = sqlite_conn.execute("SELECT id FROM events")
    valid_event_ids = {row[0] for row in cursor_events.fetchall()}

    for row in rows:
        thread_states = row["thread_states"]
        if isinstance(thread_states, str):
            thread_states = json.loads(thread_states)

        session_state = row["session_state"]
        if session_state and isinstance(session_state, str):
            session_state = json.loads(session_state)

        event_id = row["event_id"] if row["event_id"] else None
        if event_id and event_id not in valid_event_ids:
            event_id = None

        snapshot = Snapshot(
            id=row["id"],
            session_id=row["session_id"],
            event_id=event_id,
            thread_states=thread_states,
            session_state=session_state,
            created_at=row["created_at"],
            description=row["description"] if row["description"] else None,
        )
        pg_session.merge(snapshot)
    pg_session.commit()
    print(f"Migrated {len(rows)} snapshots")


if __name__ == "__main__":
    try:
        print("Starting migration from SQLite to PostgreSQL...")
        print(f"SQLite DB: {sqlite_db_path}")
        print(f"PostgreSQL URL: {pg_url}")
        print()

        migrate_users()
        migrate_threads()
        migrate_sessions()
        migrate_events()
        migrate_snapshots()

        print("\nMigration complete!")
    except Exception as e:
        print(f"\nMigration failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_session.close()
