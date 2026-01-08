#!/usr/bin/env python3
"""Migrate data from SQLite to PostgreSQL."""

import sqlite3
import os
from sqlalchemy import create_engine, text


def migrate():
    sqlite_path = "/home/josh/code/comic-pile/comic_pile.db"
    pg_url = os.getenv(
        "DATABASE_URL",
        "postgresql://comicpile:comicpile_password@localhost:5435/comicpile",
    )

    print(f"SQLite path: {sqlite_path}")
    print(f"PostgreSQL URL: {pg_url}")

    # Connect to SQLite
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    # Connect to PostgreSQL
    pg_engine = create_engine(pg_url)
    pg_conn = pg_engine.connect()
    transaction = pg_conn.begin()

    try:
        # Clear PostgreSQL tables in reverse order of dependencies
        print("\nClearing PostgreSQL tables...")
        pg_conn.execute(text("DELETE FROM events"))
        pg_conn.execute(text("DELETE FROM snapshots"))
        pg_conn.execute(text("DELETE FROM sessions"))
        pg_conn.execute(text("DELETE FROM threads"))
        pg_conn.execute(text("DELETE FROM users"))
        pg_conn.execute(text("DELETE FROM settings"))
        print("Cleared all tables")

        # Migrate users
        print("\nMigrating users...")
        sqlite_cur.execute("SELECT * FROM users")
        users = sqlite_cur.fetchall()
        print(f"  Found {len(users)} users")

        for row in users:
            pg_conn.execute(
                text(
                    "INSERT INTO users (id, username, created_at) VALUES (:id, :username, :created_at)"
                ),
                {"id": row["id"], "username": row["username"], "created_at": row["created_at"]},
            )
        print(f"  Inserted {len(users)} users")

        # Migrate threads
        print("\nMigrating threads...")
        sqlite_cur.execute("SELECT * FROM threads")
        threads = sqlite_cur.fetchall()
        print(f"  Found {len(threads)} threads")

        for row in threads:
            # Convert boolean string to Python boolean
            is_test = row["is_test"]
            if isinstance(is_test, str):
                is_test = is_test.lower() == "true"

            pg_conn.execute(
                text(
                    """INSERT INTO threads 
                       (id, title, format, issues_remaining, queue_position, status, 
                        last_rating, last_activity_at, review_url, created_at, user_id, 
                        last_review_at, notes, is_test) 
                       VALUES 
                       (:id, :title, :format, :issues_remaining, :queue_position, :status, 
                        :last_rating, :last_activity_at, :review_url, :created_at, :user_id, 
                        :last_review_at, :notes, :is_test)"""
                ),
                {
                    "id": row["id"],
                    "title": row["title"],
                    "format": row["format"],
                    "issues_remaining": row["issues_remaining"],
                    "queue_position": row["queue_position"],
                    "status": row["status"],
                    "last_rating": row["last_rating"],
                    "last_activity_at": row["last_activity_at"],
                    "review_url": row["review_url"],
                    "created_at": row["created_at"],
                    "user_id": row["user_id"],
                    "last_review_at": row["last_review_at"],
                    "notes": row["notes"],
                    "is_test": is_test,
                },
            )
        print(f"  Inserted {len(threads)} threads")

        # Migrate sessions
        print("\nMigrating sessions...")
        sqlite_cur.execute("SELECT * FROM sessions")
        sessions = sqlite_cur.fetchall()
        print(f"  Found {len(sessions)} sessions")

        # Get valid thread IDs for reference checking
        sqlite_cur.execute("SELECT id FROM threads")
        valid_thread_ids = {row[0] for row in sqlite_cur.fetchall()}

        for row in sessions:
            # Handle orphaned pending_thread_id references
            pending_thread_id = row["pending_thread_id"]
            if pending_thread_id is not None and pending_thread_id not in valid_thread_ids:
                print(
                    f"  Warning: Session {row['id']} references non-existent thread {pending_thread_id}, setting to NULL"
                )
                pending_thread_id = None

            pg_conn.execute(
                text(
                    """INSERT INTO sessions 
                       (id, started_at, ended_at, start_die, user_id, 
                        pending_thread_id, pending_thread_updated_at, manual_die) 
                       VALUES 
                       (:id, :started_at, :ended_at, :start_die, :user_id, 
                        :pending_thread_id, :pending_thread_updated_at, :manual_die)"""
                ),
                {
                    "id": row["id"],
                    "started_at": row["started_at"],
                    "ended_at": row["ended_at"],
                    "start_die": row["start_die"],
                    "user_id": row["user_id"],
                    "pending_thread_id": pending_thread_id,
                    "pending_thread_updated_at": row["pending_thread_updated_at"],
                    "manual_die": row["manual_die"],
                },
            )
        print(f"  Inserted {len(sessions)} sessions")

        # Migrate events
        print("\nMigrating events...")
        sqlite_cur.execute("SELECT * FROM events")
        events = sqlite_cur.fetchall()
        print(f"  Found {len(events)} events")

        # Get valid thread IDs for reference checking
        sqlite_cur.execute("SELECT id FROM threads")
        valid_thread_ids = {row[0] for row in sqlite_cur.fetchall()}

        for row in events:
            # Handle orphaned thread_id and selected_thread_id references
            thread_id = row["thread_id"]
            if thread_id is not None and thread_id not in valid_thread_ids:
                print(
                    f"  Warning: Event {row['id']} references non-existent thread {thread_id}, setting to NULL"
                )
                thread_id = None

            selected_thread_id = row["selected_thread_id"]
            if selected_thread_id is not None and selected_thread_id not in valid_thread_ids:
                print(
                    f"  Warning: Event {row['id']} selected non-existent thread {selected_thread_id}, setting to NULL"
                )
                selected_thread_id = None

            pg_conn.execute(
                text(
                    """INSERT INTO events 
                       (id, type, timestamp, die, result, selected_thread_id, 
                        selection_method, rating, issues_read, queue_move, die_after, 
                        session_id, thread_id) 
                       VALUES 
                       (:id, :type, :timestamp, :die, :result, :selected_thread_id, 
                        :selection_method, :rating, :issues_read, :queue_move, :die_after, 
                        :session_id, :thread_id)"""
                ),
                {
                    "id": row["id"],
                    "type": row["type"],
                    "timestamp": row["timestamp"],
                    "die": row["die"],
                    "result": row["result"],
                    "selected_thread_id": selected_thread_id,
                    "selection_method": row["selection_method"],
                    "rating": row["rating"],
                    "issues_read": row["issues_read"],
                    "queue_move": row["queue_move"],
                    "die_after": row["die_after"],
                    "session_id": row["session_id"],
                    "thread_id": thread_id,
                },
            )
        print(f"  Inserted {len(events)} events")

        # Migrate settings
        print("\nMigrating settings...")
        sqlite_cur.execute("SELECT * FROM settings")
        settings = sqlite_cur.fetchall()
        print(f"  Found {len(settings)} settings")

        for row in settings:
            pg_conn.execute(
                text(
                    """INSERT INTO settings 
                       (id, session_gap_hours, start_die, rating_min, rating_max, 
                        rating_step, rating_threshold, created_at, updated_at) 
                       VALUES 
                       (:id, :session_gap_hours, :start_die, :rating_min, :rating_max, 
                        :rating_step, :rating_threshold, :created_at, :updated_at)"""
                ),
                {
                    "id": row["id"],
                    "session_gap_hours": row["session_gap_hours"],
                    "start_die": row["start_die"],
                    "rating_min": row["rating_min"],
                    "rating_max": row["rating_max"],
                    "rating_step": row["rating_step"],
                    "rating_threshold": row["rating_threshold"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                },
            )
        print(f"  Inserted {len(settings)} settings")

        # Migrate snapshots
        print("\nMigrating snapshots...")
        sqlite_cur.execute("SELECT * FROM snapshots")
        snapshots = sqlite_cur.fetchall()
        print(f"  Found {len(snapshots)} snapshots")

        # Get valid event IDs for reference checking
        sqlite_cur.execute("SELECT id FROM events")
        valid_event_ids = {row[0] for row in sqlite_cur.fetchall()}

        for row in snapshots:
            # Handle orphaned event_id references
            event_id = row["event_id"]
            if event_id is not None and event_id not in valid_event_ids:
                print(
                    f"  Warning: Snapshot {row['id']} references non-existent event {event_id}, setting to NULL"
                )
                event_id = None

            pg_conn.execute(
                text(
                    """INSERT INTO snapshots 
                       (id, session_id, event_id, thread_states, created_at, description, session_state) 
                       VALUES 
                       (:id, :session_id, :event_id, :thread_states, :created_at, :description, :session_state)"""
                ),
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "event_id": event_id,
                    "thread_states": row["thread_states"],
                    "created_at": row["created_at"],
                    "description": row["description"],
                    "session_state": row["session_state"],
                },
            )
        print(f"  Inserted {len(snapshots)} snapshots")

        # Commit transaction
        transaction.commit()
        print("\n✓ Transaction committed successfully")

        # Verify final counts
        print("\nFinal PostgreSQL row counts:")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM users"))
        print(f"  users: {result.scalar()}")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM threads"))
        print(f"  threads: {result.scalar()}")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM events"))
        print(f"  events: {result.scalar()}")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM sessions"))
        print(f"  sessions: {result.scalar()}")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM settings"))
        print(f"  settings: {result.scalar()}")
        result = pg_conn.execute(text("SELECT COUNT(*) FROM snapshots"))
        print(f"  snapshots: {result.scalar()}")

        print("\nMigration complete!")

    except Exception as e:
        print(f"\n✗ Error during migration: {e}")
        transaction.rollback()
        raise
    finally:
        pg_conn.close()
        sqlite_conn.close()


if __name__ == "__main__":
    migrate()
