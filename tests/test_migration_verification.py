"""Migration verification tests for SQLite to PostgreSQL."""

import os
import sqlite3
import tempfile
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Event, Session, Settings, Snapshot, Task, Thread, User


def migrate_sqlite_to_postgres(sqlite_path: str, pg_db_session):
    """Migrate data from SQLite to PostgreSQL."""
    sqlite_conn = sqlite3.connect(sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    try:
        cursor = sqlite_conn.execute("SELECT * FROM users")
        for row in cursor:
            user = User(
                id=row["id"],
                username=row["username"],
                created_at=row["created_at"],
            )
            pg_db_session.merge(user)
        pg_db_session.commit()

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
            pg_db_session.merge(thread)
        pg_db_session.commit()

        cursor = sqlite_conn.execute("SELECT * FROM sessions")
        for row in cursor:
            sess = Session(
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
            pg_db_session.merge(sess)
        pg_db_session.commit()

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
            pg_db_session.merge(event)
        pg_db_session.commit()

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
            pg_db_session.merge(task)
        pg_db_session.commit()

        cursor = sqlite_conn.execute("SELECT * FROM settings")
        for row in cursor:
            setting = Settings(
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
            pg_db_session.merge(setting)
        pg_db_session.commit()

        cursor = sqlite_conn.execute("SELECT * FROM snapshots")
        for row in cursor:
            import json

            thread_states = row["thread_states"]
            if isinstance(thread_states, str):
                thread_states = json.loads(thread_states)

            session_state = row["session_state"]
            if session_state and isinstance(session_state, str):
                session_state = json.loads(session_state)

            event_id = row["event_id"] if row["event_id"] else None

            snapshot = Snapshot(
                id=row["id"],
                session_id=row["session_id"],
                event_id=event_id,
                thread_states=thread_states,
                session_state=session_state,
                created_at=row["created_at"],
                description=row["description"] if row["description"] else None,
            )
            pg_db_session.merge(snapshot)
        pg_db_session.commit()
    finally:
        sqlite_conn.close()


@pytest.fixture(scope="function")
def sqlite_db_path():
    """Create temporary SQLite database path."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture(scope="function")
def sqlite_connection(sqlite_db_path):
    """Create SQLite connection with sample data."""
    conn = sqlite3.connect(sqlite_db_path)
    conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    now = datetime.now(UTC)
    now_iso = now.isoformat()

    cursor.execute(
        """CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP
    )"""
    )

    cursor.execute(
        """CREATE TABLE threads (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        format TEXT NOT NULL,
        issues_remaining INTEGER DEFAULT 0,
        queue_position INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        last_rating REAL,
        last_activity_at TIMESTAMP,
        review_url TEXT,
        last_review_at TIMESTAMP,
        created_at TIMESTAMP,
        user_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )"""
    )

    cursor.execute(
        """CREATE TABLE sessions (
        id INTEGER PRIMARY KEY,
        started_at TIMESTAMP,
        ended_at TIMESTAMP,
        start_die INTEGER,
        manual_die INTEGER,
        user_id INTEGER NOT NULL,
        pending_thread_id INTEGER,
        pending_thread_updated_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id),
        FOREIGN KEY (pending_thread_id) REFERENCES threads (id)
    )"""
    )

    cursor.execute(
        """CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        type TEXT,
        timestamp TIMESTAMP,
        die INTEGER,
        result INTEGER,
        selected_thread_id INTEGER,
        selection_method TEXT,
        rating REAL,
        issues_read INTEGER,
        queue_move TEXT,
        die_after INTEGER,
        session_id INTEGER NOT NULL,
        thread_id INTEGER NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (thread_id) REFERENCES threads (id),
        FOREIGN KEY (selected_thread_id) REFERENCES threads (id)
    )"""
    )

    cursor.execute(
        """CREATE TABLE tasks (
        id INTEGER PRIMARY KEY,
        task_id TEXT UNIQUE,
        title TEXT NOT NULL,
        description TEXT,
        priority TEXT NOT NULL,
        status TEXT NOT NULL,
        dependencies TEXT,
        assigned_agent TEXT,
        worktree TEXT,
        status_notes TEXT,
        estimated_effort TEXT,
        completed BOOLEAN NOT NULL,
        blocked_reason TEXT,
        blocked_by TEXT,
        last_heartbeat TIMESTAMP,
        instructions TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )"""
    )

    cursor.execute(
        """CREATE TABLE settings (
        id INTEGER PRIMARY KEY,
        session_gap_hours INTEGER NOT NULL,
        start_die INTEGER NOT NULL,
        rating_min REAL NOT NULL,
        rating_max REAL NOT NULL,
        rating_step REAL NOT NULL,
        rating_threshold REAL NOT NULL,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )"""
    )

    cursor.execute(
        """CREATE TABLE snapshots (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        event_id INTEGER,
        thread_states TEXT NOT NULL,
        session_state TEXT,
        created_at TIMESTAMP,
        description TEXT,
        FOREIGN KEY (session_id) REFERENCES sessions (id),
        FOREIGN KEY (event_id) REFERENCES events (id)
    )"""
    )

    cursor.execute(
        "INSERT INTO users (id, username, created_at) VALUES (?, ?, ?)",
        (1, "test_user", now_iso),
    )
    cursor.execute(
        "INSERT INTO users (id, username, created_at) VALUES (?, ?, ?)",
        (2, "second_user", now_iso),
    )

    cursor.execute(
        """INSERT INTO threads 
        (id, title, format, issues_remaining, queue_position, status, 
         last_rating, last_activity_at, review_url, last_review_at, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1,
            "Superman",
            "Comic",
            10,
            1,
            "active",
            4.5,
            now_iso,
            "https://example.com/superman",
            now_iso,
            now_iso,
            1,
        ),
    )
    cursor.execute(
        """INSERT INTO threads 
        (id, title, format, issues_remaining, queue_position, status, 
         last_rating, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (2, "Batman", "Comic", 5, 2, "active", None, now_iso, 1),
    )
    cursor.execute(
        """INSERT INTO threads 
        (id, title, format, issues_remaining, queue_position, status, 
         created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (3, "Wonder Woman", "Trade Paperback", 0, 3, "completed", now_iso, 2),
    )

    cursor.execute(
        """INSERT INTO sessions 
        (id, started_at, ended_at, start_die, manual_die, user_id, 
         pending_thread_id, pending_thread_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, now_iso, None, 6, None, 1, None, None),
    )
    cursor.execute(
        """INSERT INTO sessions 
        (id, started_at, start_die, user_id, pending_thread_id)
        VALUES (?, ?, ?, ?, ?)""",
        (2, now_iso, 8, 1, 1),
    )

    cursor.execute(
        """INSERT INTO events 
        (id, type, timestamp, die, result, selected_thread_id, 
         selection_method, rating, issues_read, queue_move, die_after, 
         session_id, thread_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, "roll", now_iso, 6, 4, 1, "random", None, None, None, None, 1, 1),
    )
    cursor.execute(
        """INSERT INTO events 
        (id, type, timestamp, rating, issues_read, queue_move, die_after, 
         session_id, thread_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (2, "rate", now_iso, 4.5, 1, "back", 8, 1, 1),
    )

    cursor.execute(
        """INSERT INTO tasks 
        (id, task_id, title, description, priority, status, 
         dependencies, assigned_agent, worktree, status_notes, 
         estimated_effort, completed, blocked_reason, blocked_by, 
         last_heartbeat, instructions, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            1,
            "TASK-101",
            "Test Task 1",
            "Description for task 1",
            "HIGH",
            "pending",
            None,
            "worker1",
            "/path/to/worktree",
            "Working on it",
            "2 hours",
            False,
            None,
            None,
            None,
            "Do this task",
            now_iso,
            now_iso,
        ),
    )
    cursor.execute(
        """INSERT INTO tasks 
        (id, task_id, title, description, priority, status, 
         estimated_effort, completed, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (2, "TASK-102", "Test Task 2", None, "MEDIUM", "done", "1 hour", True, now_iso, now_iso),
    )

    cursor.execute(
        """INSERT INTO settings 
        (id, session_gap_hours, start_die, rating_min, rating_max, 
         rating_step, rating_threshold, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, 24, 6, 1.0, 5.0, 0.5, 3.5, now_iso, now_iso),
    )

    import json

    thread_states_1 = json.dumps(
        [{"id": 1, "queue_position": 1, "issues_remaining": 10, "status": "active"}]
    )
    thread_states_2 = json.dumps(
        [
            {"id": 1, "queue_position": 2, "issues_remaining": 9, "status": "active"},
            {"id": 2, "queue_position": 1, "issues_remaining": 5, "status": "active"},
        ]
    )
    session_state_1 = json.dumps({"start_die": 6, "manual_die": None})

    cursor.execute(
        """INSERT INTO snapshots 
        (id, session_id, event_id, thread_states, session_state, created_at, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (1, 1, 1, thread_states_1, session_state_1, now_iso, "Session start snapshot"),
    )
    cursor.execute(
        """INSERT INTO snapshots 
        (id, session_id, event_id, thread_states, session_state, created_at, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (2, 1, 2, thread_states_2, session_state_1, now_iso, "After first roll"),
    )

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture(scope="function")
def postgres_db(sqlite_db_path):
    """Create PostgreSQL test database and migrate from SQLite."""
    pg_url = os.getenv("TEST_DATABASE_URL")
    if not pg_url or not pg_url.startswith("postgresql"):
        pytest.skip("PostgreSQL test database not configured")

    engine = create_engine(pg_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = sessionmaker(bind=engine)()

    migrate_sqlite_to_postgres(sqlite_db_path, session)

    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_migration_row_counts_match(sqlite_connection, postgres_db):
    """Test that row counts match between SQLite and PostgreSQL after migration."""
    sqlite_counts = {}
    cursor = sqlite_connection.cursor()

    for table in ["users", "threads", "sessions", "events", "tasks", "settings", "snapshots"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        sqlite_counts[table] = cursor.fetchone()[0]

    for table in ["users", "threads", "sessions", "events", "tasks", "settings", "snapshots"]:
        pg_count = postgres_db.execute(f"SELECT COUNT(*) FROM {table}").scalar()
        assert pg_count == sqlite_counts[table], f"Row count mismatch for {table}"


def test_migration_users_data_integrity(sqlite_connection, postgres_db):
    """Test that users data is migrated correctly."""
    sqlite_users = sqlite_connection.execute("SELECT * FROM users ORDER BY id").fetchall()
    pg_users = postgres_db.execute("SELECT * FROM users ORDER BY id").all()

    assert len(sqlite_users) == len(pg_users)

    for sqlite_user, pg_user in zip(sqlite_users, pg_users, strict=True):
        assert pg_user.id == sqlite_user["id"]
        assert pg_user.username == sqlite_user["username"]
        assert pg_user.created_at is not None


def test_migration_threads_data_integrity(sqlite_connection, postgres_db):
    """Test that threads data is migrated correctly."""
    sqlite_threads = sqlite_connection.execute("SELECT * FROM threads ORDER BY id").fetchall()
    pg_threads = postgres_db.execute("SELECT * FROM threads ORDER BY id").all()

    assert len(sqlite_threads) == len(pg_threads)

    for sqlite_thread, pg_thread in zip(sqlite_threads, pg_threads, strict=True):
        assert pg_thread.id == sqlite_thread["id"]
        assert pg_thread.title == sqlite_thread["title"]
        assert pg_thread.format == sqlite_thread["format"]
        assert pg_thread.issues_remaining == sqlite_thread["issues_remaining"]
        assert pg_thread.queue_position == sqlite_thread["queue_position"]
        assert pg_thread.status == sqlite_thread["status"]

        if sqlite_thread["last_rating"] is not None:
            assert pg_thread.last_rating == sqlite_thread["last_rating"]
        else:
            assert pg_thread.last_rating is None

        if sqlite_thread["last_activity_at"] is not None:
            assert pg_thread.last_activity_at is not None
        else:
            assert pg_thread.last_activity_at is None

        if sqlite_thread["review_url"] is not None:
            assert pg_thread.review_url == sqlite_thread["review_url"]
        else:
            assert pg_thread.review_url is None

        if sqlite_thread["last_review_at"] is not None:
            assert pg_thread.last_review_at is not None
        else:
            assert pg_thread.last_review_at is None

        assert pg_thread.user_id == sqlite_thread["user_id"]


def test_migration_sessions_data_integrity(sqlite_connection, postgres_db):
    """Test that sessions data is migrated correctly."""
    sqlite_sessions = sqlite_connection.execute("SELECT * FROM sessions ORDER BY id").fetchall()
    pg_sessions = postgres_db.execute("SELECT * FROM sessions ORDER BY id").all()

    assert len(sqlite_sessions) == len(pg_sessions)

    for sqlite_session, pg_session in zip(sqlite_sessions, pg_sessions, strict=True):
        assert pg_session.id == sqlite_session["id"]
        assert pg_session.start_die == sqlite_session["start_die"]
        assert pg_session.user_id == sqlite_session["user_id"]

        if sqlite_session["ended_at"] is not None:
            assert pg_session.ended_at is not None
        else:
            assert pg_session.ended_at is None

        if sqlite_session["manual_die"] is not None:
            assert pg_session.manual_die == sqlite_session["manual_die"]
        else:
            assert pg_session.manual_die is None

        if sqlite_session["pending_thread_id"] is not None:
            assert pg_session.pending_thread_id == sqlite_session["pending_thread_id"]
        else:
            assert pg_session.pending_thread_id is None

        if sqlite_session["pending_thread_updated_at"] is not None:
            assert pg_session.pending_thread_updated_at is not None
        else:
            assert pg_session.pending_thread_updated_at is None


def test_migration_events_data_integrity(sqlite_connection, postgres_db):
    """Test that events data is migrated correctly."""
    sqlite_events = sqlite_connection.execute("SELECT * FROM events ORDER BY id").fetchall()
    pg_events = postgres_db.execute("SELECT * FROM events ORDER BY id").all()

    assert len(sqlite_events) == len(pg_events)

    for sqlite_event, pg_event in zip(sqlite_events, pg_events, strict=True):
        assert pg_event.id == sqlite_event["id"]
        assert pg_event.type == sqlite_event["type"]
        assert pg_event.session_id == sqlite_event["session_id"]
        assert pg_event.thread_id == sqlite_event["thread_id"]

        if sqlite_event["die"] is not None:
            assert pg_event.die == sqlite_event["die"]
        else:
            assert pg_event.die is None

        if sqlite_event["result"] is not None:
            assert pg_event.result == sqlite_event["result"]
        else:
            assert pg_event.result is None

        if sqlite_event["selected_thread_id"] is not None:
            assert pg_event.selected_thread_id == sqlite_event["selected_thread_id"]
        else:
            assert pg_event.selected_thread_id is None

        if sqlite_event["selection_method"] is not None:
            assert pg_event.selection_method == sqlite_event["selection_method"]
        else:
            assert pg_event.selection_method is None

        if sqlite_event["rating"] is not None:
            assert pg_event.rating == sqlite_event["rating"]
        else:
            assert pg_event.rating is None

        if sqlite_event["issues_read"] is not None:
            assert pg_event.issues_read == sqlite_event["issues_read"]
        else:
            assert pg_event.issues_read is None

        if sqlite_event["queue_move"] is not None:
            assert pg_event.queue_move == sqlite_event["queue_move"]
        else:
            assert pg_event.queue_move is None

        if sqlite_event["die_after"] is not None:
            assert pg_event.die_after == sqlite_event["die_after"]
        else:
            assert pg_event.die_after is None


def test_migration_tasks_data_integrity(sqlite_connection, postgres_db):
    """Test that tasks data is migrated correctly."""
    sqlite_tasks = sqlite_connection.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    pg_tasks = postgres_db.execute("SELECT * FROM tasks ORDER BY id").all()

    assert len(sqlite_tasks) == len(pg_tasks)

    for sqlite_task, pg_task in zip(sqlite_tasks, pg_tasks, strict=True):
        assert pg_task.id == sqlite_task["id"]
        assert pg_task.task_id == sqlite_task["task_id"]
        assert pg_task.title == sqlite_task["title"]
        assert pg_task.priority == sqlite_task["priority"]
        assert pg_task.status == sqlite_task["status"]
        assert pg_task.estimated_effort == sqlite_task["estimated_effort"]
        assert pg_task.completed == sqlite_task["completed"]

        if sqlite_task["description"] is not None:
            assert pg_task.description == sqlite_task["description"]
        else:
            assert pg_task.description is None

        if sqlite_task["dependencies"] is not None:
            assert pg_task.dependencies == sqlite_task["dependencies"]
        else:
            assert pg_task.dependencies is None

        if sqlite_task["assigned_agent"] is not None:
            assert pg_task.assigned_agent == sqlite_task["assigned_agent"]
        else:
            assert pg_task.assigned_agent is None

        if sqlite_task["worktree"] is not None:
            assert pg_task.worktree == sqlite_task["worktree"]
        else:
            assert pg_task.worktree is None

        if sqlite_task["status_notes"] is not None:
            assert pg_task.status_notes == sqlite_task["status_notes"]
        else:
            assert pg_task.status_notes is None

        if sqlite_task["blocked_reason"] is not None:
            assert pg_task.blocked_reason == sqlite_task["blocked_reason"]
        else:
            assert pg_task.blocked_reason is None

        if sqlite_task["blocked_by"] is not None:
            assert pg_task.blocked_by == sqlite_task["blocked_by"]
        else:
            assert pg_task.blocked_by is None

        if sqlite_task["last_heartbeat"] is not None:
            assert pg_task.last_heartbeat is not None
        else:
            assert pg_task.last_heartbeat is None

        if sqlite_task["instructions"] is not None:
            assert pg_task.instructions == sqlite_task["instructions"]
        else:
            assert pg_task.instructions is None


def test_migration_settings_data_integrity(sqlite_connection, postgres_db):
    """Test that settings data is migrated correctly."""
    sqlite_settings = sqlite_connection.execute("SELECT * FROM settings ORDER BY id").fetchall()
    pg_settings = postgres_db.execute("SELECT * FROM settings ORDER BY id").all()

    assert len(sqlite_settings) == len(pg_settings)

    for sqlite_setting, pg_setting in zip(sqlite_settings, pg_settings, strict=True):
        assert pg_setting.id == sqlite_setting["id"]
        assert pg_setting.session_gap_hours == sqlite_setting["session_gap_hours"]
        assert pg_setting.start_die == sqlite_setting["start_die"]
        assert pg_setting.rating_min == sqlite_setting["rating_min"]
        assert pg_setting.rating_max == sqlite_setting["rating_max"]
        assert pg_setting.rating_step == sqlite_setting["rating_step"]
        assert pg_setting.rating_threshold == sqlite_setting["rating_threshold"]


def test_migration_snapshots_data_integrity(sqlite_connection, postgres_db):
    """Test that snapshots data is migrated correctly."""
    import json

    sqlite_snapshots = sqlite_connection.execute("SELECT * FROM snapshots ORDER BY id").fetchall()
    pg_snapshots = postgres_db.execute("SELECT * FROM snapshots ORDER BY id").all()

    assert len(sqlite_snapshots) == len(pg_snapshots)

    for sqlite_snapshot, pg_snapshot in zip(sqlite_snapshots, pg_snapshots, strict=True):
        assert pg_snapshot.id == sqlite_snapshot["id"]
        assert pg_snapshot.session_id == sqlite_snapshot["session_id"]

        if sqlite_snapshot["event_id"] is not None:
            assert pg_snapshot.event_id == sqlite_snapshot["event_id"]
        else:
            assert pg_snapshot.event_id is None

        sqlite_thread_states = sqlite_snapshot["thread_states"]
        if isinstance(sqlite_thread_states, str):
            sqlite_thread_states = json.loads(sqlite_thread_states)
        assert pg_snapshot.thread_states == sqlite_thread_states

        sqlite_session_state = sqlite_snapshot["session_state"]
        if sqlite_session_state and isinstance(sqlite_session_state, str):
            sqlite_session_state = json.loads(sqlite_session_state)
        if sqlite_session_state is not None:
            assert pg_snapshot.session_state == sqlite_session_state
        else:
            assert pg_snapshot.session_state is None

        if sqlite_snapshot["description"] is not None:
            assert pg_snapshot.description == sqlite_snapshot["description"]
        else:
            assert pg_snapshot.description is None


def test_migration_foreign_key_relationships(sqlite_connection, postgres_db):
    """Test that foreign key relationships are preserved."""
    sqlite_users = sqlite_connection.execute("SELECT id FROM users ORDER BY id").fetchall()
    pg_users = postgres_db.execute("SELECT id FROM users ORDER BY id").all()

    for sqlite_user, pg_user in zip(sqlite_users, pg_users, strict=True):
        sqlite_thread_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM threads WHERE user_id = ?", (sqlite_user["id"],)
        ).fetchone()[0]
        sqlite_session_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (sqlite_user["id"],)
        ).fetchone()[0]

        pg_thread_count = postgres_db.execute(
            "SELECT COUNT(*) FROM threads WHERE user_id = ?", (pg_user.id,)
        ).scalar()
        pg_session_count = postgres_db.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ?", (pg_user.id,)
        ).scalar()

        assert pg_thread_count == sqlite_thread_count
        assert pg_session_count == sqlite_session_count

    sqlite_threads = sqlite_connection.execute("SELECT id FROM threads ORDER BY id").fetchall()
    pg_threads = postgres_db.execute("SELECT id FROM threads ORDER BY id").all()

    for sqlite_thread, pg_thread in zip(sqlite_threads, pg_threads, strict=True):
        sqlite_event_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM events WHERE thread_id = ?", (sqlite_thread["id"],)
        ).fetchone()[0]
        pg_event_count = postgres_db.execute(
            "SELECT COUNT(*) FROM events WHERE thread_id = ?", (pg_thread.id,)
        ).scalar()

        assert pg_event_count == sqlite_event_count

    sqlite_sessions = sqlite_connection.execute("SELECT id FROM sessions ORDER BY id").fetchall()
    pg_sessions = postgres_db.execute("SELECT id FROM sessions ORDER BY id").all()

    for sqlite_session, pg_session in zip(sqlite_sessions, pg_sessions, strict=True):
        sqlite_event_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = ?", (sqlite_session["id"],)
        ).fetchone()[0]
        pg_event_count = postgres_db.execute(
            "SELECT COUNT(*) FROM events WHERE session_id = ?", (pg_session.id,)
        ).scalar()

        assert pg_event_count == sqlite_event_count

        sqlite_snapshot_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM snapshots WHERE session_id = ?", (sqlite_session["id"],)
        ).fetchone()[0]
        pg_snapshot_count = postgres_db.execute(
            "SELECT COUNT(*) FROM snapshots WHERE session_id = ?", (pg_session.id,)
        ).scalar()

        assert pg_snapshot_count == sqlite_snapshot_count

    sqlite_events = sqlite_connection.execute(
        "SELECT id FROM events WHERE event_id IS NOT NULL ORDER BY id"
    ).fetchall()
    pg_events = postgres_db.execute(
        "SELECT id FROM events WHERE event_id IS NOT NULL ORDER BY id"
    ).all()

    for sqlite_event, pg_event in zip(sqlite_events, pg_events, strict=True):
        sqlite_snapshot_count = sqlite_connection.execute(
            "SELECT COUNT(*) FROM snapshots WHERE event_id = ?", (sqlite_event["id"],)
        ).fetchone()[0]
        pg_snapshot_count = postgres_db.execute(
            "SELECT COUNT(*) FROM snapshots WHERE event_id = ?", (pg_event.id,)
        ).scalar()

        assert pg_snapshot_count == sqlite_snapshot_count


def test_migration_with_empty_tables(sqlite_connection, postgres_db):
    """Test migration with some tables empty."""
    sqlite_connection.execute("DELETE FROM tasks")
    sqlite_connection.execute("DELETE FROM settings")
    sqlite_connection.commit()

    pg_task_count = postgres_db.execute("SELECT COUNT(*) FROM tasks").scalar()
    pg_setting_count = postgres_db.execute("SELECT COUNT(*) FROM settings").scalar()

    assert pg_task_count == 0
    assert pg_setting_count == 0


def test_migration_with_null_values(sqlite_connection, postgres_db):
    """Test migration with nullable fields set to NULL."""
    sqlite_threads = sqlite_connection.execute(
        "SELECT * FROM threads WHERE last_rating IS NULL"
    ).fetchall()

    assert len(sqlite_threads) > 0

    pg_threads = postgres_db.execute("SELECT * FROM threads WHERE last_rating IS NULL").all()

    assert len(pg_threads) == len(sqlite_threads)

    for _sqlite_thread, pg_thread in zip(sqlite_threads, pg_threads, strict=True):
        assert pg_thread.last_rating is None


def test_migration_data_consistency(sqlite_connection, postgres_db):
    """Test that data is consistent across both databases."""
    sqlite_thread_avg = sqlite_connection.execute(
        "SELECT AVG(last_rating) FROM threads WHERE last_rating IS NOT NULL"
    ).fetchone()[0]
    pg_thread_avg = postgres_db.execute(
        "SELECT AVG(last_rating) FROM threads WHERE last_rating IS NOT NULL"
    ).scalar()

    if sqlite_thread_avg is not None:
        assert abs(pg_thread_avg - sqlite_thread_avg) < 0.0001

    sqlite_active_count = sqlite_connection.execute(
        "SELECT COUNT(*) FROM threads WHERE status = 'active'"
    ).fetchone()[0]
    pg_active_count = postgres_db.execute(
        "SELECT COUNT(*) FROM threads WHERE status = 'active'"
    ).scalar()

    assert pg_active_count == sqlite_active_count
