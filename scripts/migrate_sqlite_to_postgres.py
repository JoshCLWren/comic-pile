"""Migrate data from SQLite to PostgreSQL."""

import os
import sqlite3
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Event, Session, Settings, Task, Thread, User

sqlite_conn = sqlite3.connect("/home/josh/code/comic-pile/comic_pile.db")
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
            last_rating=row["last_rating"],
            last_activity_at=row["last_activity_at"],
            review_url=row["review_url"],
            last_review_at=row["last_review_at"],
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
            ended_at=row["ended_at"],
            start_die=row["start_die"],
            user_id=row["user_id"],
            pending_thread_id=row["pending_thread_id"],
            pending_thread_updated_at=row["pending_thread_updated_at"],
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
            die=row["die"],
            result=row["result"],
            selected_thread_id=row["selected_thread_id"],
            selection_method=row["selection_method"],
            rating=row["rating"],
            issues_read=row["issues_read"],
            queue_move=row["queue_move"],
            die_after=row["die_after"],
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
            description=row["description"],
            priority=row["priority"],
            status=row["status"],
            dependencies=row["dependencies"],
            assigned_agent=row["assigned_agent"],
            worktree=row["worktree"],
            status_notes=row["status_notes"],
            estimated_effort=row["estimated_effort"],
            completed=row["completed"],
            blocked_reason=row["blocked_reason"],
            blocked_by=row["blocked_by"],
            last_heartbeat=row["last_heartbeat"],
            instructions=row["instructions"],
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
    print("Starting migration from SQLite to PostgreSQL...")
    migrate_users()
    migrate_threads()
    migrate_sessions()
    migrate_events()
    migrate_tasks()
    migrate_settings()
    print("Migration complete!")
    sqlite_conn.close()
    pg_session.close()
