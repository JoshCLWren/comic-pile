#!/usr/bin/env python3
"""Migrate threads from cleaned JSON export to PostgreSQL production database."""

import json
import psycopg


def migrate_threads_to_postgres():
    """Migrate threads from cleaned JSON export to PostgreSQL production database."""
    db_config = {
        "host": "localhost",
        "port": 5434,
        "database": "comicpile",
        "user": "comicpile",
        "password": "comicpile_password",
    }

    with open("/home/josh/backups/clean_threads_for_migration.json") as f:
        data = json.load(f)

    threads = data["threads"]
    sessions = data["sessions"]
    events = data["events"]

    print(f"Loading {len(threads)} threads...")
    print(f"Loading {len(sessions)} sessions...")
    print(f"Loading {len(events)} events...")

    conn = psycopg.connect(**db_config)
    conn.autocommit = False
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id FROM users WHERE id = 1")
        if not cursor.fetchone():
            print("\nCreating user_id=1...")
            cursor.execute(
                "INSERT INTO users (id, username, created_at) VALUES (1, 'demo_user', %s)",
                ("2025-12-31 15:55:45.327747",),
            )
            print("  ✓ Created user_id=1 (username: demo_user)")

        print("\nClearing existing data for user_id=1...")
        cursor.execute(
            "DELETE FROM events WHERE session_id IN (SELECT id FROM sessions WHERE user_id = 1)"
        )
        deleted_events = cursor.rowcount
        print(f"  ✓ Deleted {deleted_events} events")

        cursor.execute("DELETE FROM sessions WHERE user_id = 1")
        deleted_sessions = cursor.rowcount
        print(f"  ✓ Deleted {deleted_sessions} sessions")

        cursor.execute("DELETE FROM threads WHERE user_id = 1")
        deleted_threads = cursor.rowcount
        print(f"  ✓ Deleted {deleted_threads} threads")

        sorted_threads = sorted(threads, key=lambda t: t["queue_position"])

        print("\nImporting threads...")
        thread_values = []
        for idx, thread in enumerate(sorted_threads, start=1):
            thread_values.append(
                (
                    thread["title"],
                    thread.get("format"),
                    thread.get("issues_remaining"),
                    idx,
                    thread.get("status", "active"),
                    thread.get("last_rating"),
                    thread.get("last_activity_at"),
                    thread.get("review_url"),
                    thread.get("last_review_at"),
                    thread.get("created_at"),
                    1,
                )
            )

        cursor.executemany(
            """
            INSERT INTO threads (
                title, format, issues_remaining, queue_position, status,
                last_rating, last_activity_at, review_url, last_review_at,
                created_at, user_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            thread_values,
        )

        cursor.execute("SELECT id FROM threads WHERE user_id = 1 ORDER BY queue_position")
        pg_thread_ids = [row[0] for row in cursor.fetchall()]

        sqlite_to_pg_thread_ids = {}
        for sqlite_thread, pg_id in zip(sorted_threads, pg_thread_ids, strict=True):
            sqlite_to_pg_thread_ids[sqlite_thread["id"]] = pg_id

        print(f"  ✓ Inserted {len(thread_values)} threads")

        print("\nImporting sessions...")
        session_values = []
        for session in sessions:
            pg_pending_thread_id = sqlite_to_pg_thread_ids.get(session.get("pending_thread_id"))
            session_values.append(
                (
                    session.get("started_at"),
                    session.get("ended_at"),
                    session.get("start_die"),
                    1,
                    pg_pending_thread_id,
                    session.get("pending_thread_updated_at"),
                    session.get("manual_die"),
                )
            )

        cursor.executemany(
            """
            INSERT INTO sessions (
                started_at, ended_at, start_die, user_id,
                pending_thread_id, pending_thread_updated_at, manual_die
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            session_values,
        )
        print(f"  ✓ Inserted {len(session_values)} sessions")

        cursor.execute("SELECT id FROM sessions WHERE user_id = 1 ORDER BY started_at")
        pg_session_ids = [row[0] for row in cursor.fetchall()]

        sorted_sessions = sorted(sessions, key=lambda s: s["id"])
        session_id_map = {}
        for sqlite_session, pg_id in zip(sorted_sessions, pg_session_ids, strict=True):
            session_id_map[sqlite_session["id"]] = pg_id

        print("\nImporting events...")
        event_values = []
        for event in events:
            pg_session_id = session_id_map.get(event["session_id"])
            pg_thread_id = (
                sqlite_to_pg_thread_ids.get(event.get("thread_id"))
                if event.get("thread_id")
                else None
            )
            pg_selected_thread_id = (
                sqlite_to_pg_thread_ids.get(event.get("selected_thread_id"))
                if event.get("selected_thread_id")
                else None
            )

            if pg_session_id:
                event_values.append(
                    (
                        event.get("type"),
                        event.get("timestamp"),
                        event.get("die"),
                        event.get("result"),
                        pg_selected_thread_id,
                        event.get("selection_method"),
                        event.get("rating"),
                        event.get("issues_read"),
                        event.get("queue_move"),
                        event.get("die_after"),
                        pg_session_id,
                        pg_thread_id,
                    )
                )

        cursor.executemany(
            """
            INSERT INTO events (
                type, timestamp, die, result, selected_thread_id,
                selection_method, rating, issues_read, queue_move,
                die_after, session_id, thread_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            event_values,
        )
        print(f"  ✓ Inserted {len(event_values)} events")

        conn.commit()
        print("\n✓ Migration completed successfully!")

    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

    print("\nVerifying import...")
    conn = psycopg.connect(**db_config)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM threads WHERE user_id = 1")
    row = cursor.fetchone()
    assert row is not None
    thread_count = row[0]
    print(f"Threads in PostgreSQL (user_id=1): {thread_count}")

    cursor.execute("""
        SELECT title, queue_position, status
        FROM threads
        WHERE user_id = 1
        ORDER BY queue_position
        LIMIT 10
    """)
    first_10 = cursor.fetchall()
    print("\nFirst 10 threads:")
    for idx, (title, pos, status) in enumerate(first_10, 1):
        print(f"  {idx}. {title} (pos={pos}, status={status})")

    cursor.execute("SELECT id, title FROM threads WHERE user_id = 1 AND title ILIKE '%Daredevil%'")
    daredevil = cursor.fetchone()
    if daredevil:
        print(f"\n✓ Daredevil found: ID={daredevil[0]}, Title={daredevil[1]}")
    else:
        print("\n✗ Daredevil NOT found")

    cursor.execute("""
        SELECT queue_position, COUNT(*)
        FROM threads
        WHERE user_id = 1
        GROUP BY queue_position
        ORDER BY queue_position
        LIMIT 5
    """)
    positions = cursor.fetchall()
    print("\nQueue positions distribution (first 5):")
    for pos, count in positions:
        print(f"  Position {pos}: {count} threads")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    migrate_threads_to_postgres()
