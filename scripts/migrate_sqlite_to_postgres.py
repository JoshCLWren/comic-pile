"""Migrate data from SQLite to PostgreSQL."""

import os
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Event, Session, Settings, Task, Thread, User

sqlite_db_path = os.getenv("SQLITE_DB_PATH", "comic_pile.db")
if not os.path.isabs(sqlite_db_path):
    sqlite_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), sqlite_db_path)

sqlite_conn = sqlite3.connect(sqlite_db_path)
sqlite_conn.row_factory = sqlite3.Row

pg_url = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://comicpile:comicpile_password@localhost:5432/comicpile"
)
pg_engine = create_engine(pg_url)
pg_session = sessionmaker(bind=pg_engine)()


def migrate_users():
    """Migrate users table."""
    cursor = sqlite_conn.execute("SELECT * FROM users")
    for row in cursor:
        user = User(
            id=row["id"],
            username=row["username"],
            created_at=row["created_at"],
        )
        pg_session.merge(user)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} users")


def migrate_threads():
    """Migrate threads table."""
    cursor = sqlite_conn.execute("SELECT * FROM threads")
    for row in cursor:
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
            created_at=row["created_at"],
            user_id=row["user_id"],
        )
        pg_session.merge(thread)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} threads")


def migrate_sessions():
    """Migrate sessions table."""
    cursor = sqlite_conn.execute("SELECT * FROM sessions")
    for row in cursor:
        session = Session(
            id=row["id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"] if row["ended_at"] else None,
            start_die=row["start_die"],
            manual_die=row["manual_die"] if row["manual_die"] else None,
            user_id=row["user_id"],
            pending_thread_id=row["pending_thread_id"] if row["pending_thread_id"] else None,
            pending_thread_updated_at=row["pending_thread_updated_at"]
            if row["pending_thread_updated_at"]
            else None,
        )
        pg_session.merge(session)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} sessions")


def migrate_events():
    """Migrate events table."""
    cursor = sqlite_conn.execute("SELECT * FROM events")
    for row in cursor:
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
    print(f"Migrated {cursor.rowcount} events")


def migrate_tasks():
    """Migrate tasks table."""
    cursor = sqlite_conn.execute("SELECT * FROM tasks")
    for row in cursor:
        task = Task(
            id=row["id"],
            task_id=row["task_id"],
            title=row["title"],
            description=row["description"] if row["description"] else None,
            priority=row["priority"],
            status=row["status"],
            dependencies=row["dependencies"] if row["dependencies"] else None,
            assigned_agent=row["assigned_agent"] if row["assigned_agent"] else None,
            worktree=row["worktree"] if row["worktree"] else None,
            status_notes=row["status_notes"] if row["status_notes"] else None,
            estimated_effort=row["estimated_effort"],
            completed=row["completed"],
            blocked_reason=row["blocked_reason"] if row["blocked_reason"] else None,
            blocked_by=row["blocked_by"] if row["blocked_by"] else None,
            last_heartbeat=row["last_heartbeat"] if row["last_heartbeat"] else None,
            instructions=row["instructions"] if row["instructions"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        pg_session.merge(task)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} tasks")


def migrate_settings():
    """Migrate settings table."""
    cursor = sqlite_conn.execute("SELECT * FROM settings")
    for row in cursor:
        settings = Settings(
            id=row["id"],
            session_gap_hours=row["session_gap_hours"],
            start_die=row["start_die"],
            rating_min=row["rating_min"],
            rating_max=row["rating_max"],
            rating_step=row["rating_step"],
            rating_threshold=row["rating_threshold"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        pg_session.merge(settings)
    pg_session.commit()
    print(f"Migrated {cursor.rowcount} settings")


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
        migrate_tasks()
        migrate_settings()

        print("\nMigration complete!")
    except Exception as e:
        print(f"\nMigration failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_session.close()
