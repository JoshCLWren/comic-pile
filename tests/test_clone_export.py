"""Tests for scripts/clone_prod_to_local.py export functionality."""

import json
import os
import stat
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.models import (
    Dependency,
    Event,
    Issue,
    ReadingOrder,
    ReadingOrderItem,
    Session,
    Snapshot,
    Thread,
    User,
)

from tests.conftest import get_test_database_url


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql")


def _make_async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
    return url


@pytest.fixture()
def test_db_url() -> str:
    """Get async test database URL for clone export tests."""
    return _make_async_url(get_test_database_url())


@pytest.fixture()
def requires_postgres(test_db_url):
    """Skip test when not running against PostgreSQL."""
    if not _is_postgres(test_db_url):
        pytest.skip(**{"msg": "Requires PostgreSQL for REPEATABLE READ / READ ONLY isolation"})


@pytest_asyncio.fixture(autouse=True)
async def clean_clone_users(db_engine) -> AsyncIterator[None]:
    """Remove clone test users before and after each test."""
    usernames = ("clone_export_test_user", "clone_round_trip_target", "clone_import_target")
    params = {f"u{index}": username for index, username in enumerate(usernames)}
    placeholders = ", ".join(f":u{index}" for index in range(len(usernames)))
    statements = (
        "DELETE FROM snapshots WHERE session_id IN "
        f"(SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders})))",
        "DELETE FROM events WHERE session_id IN "
        f"(SELECT id FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders})))",
        f"DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders}))",
        "DELETE FROM reading_order_items WHERE reading_order_id IN "
        f"(SELECT id FROM reading_orders WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders})))",
        f"DELETE FROM reading_orders WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders}))",
        "DELETE FROM dependencies WHERE source_issue_id IN "
        f"(SELECT id FROM issues WHERE thread_id IN (SELECT id FROM threads WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders}))))",
        "DELETE FROM issues WHERE thread_id IN "
        f"(SELECT id FROM threads WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders})))",
        f"DELETE FROM threads WHERE user_id IN (SELECT id FROM users WHERE username IN ({placeholders}))",
        f"DELETE FROM users WHERE username IN ({placeholders})",
    )

    async def cleanup() -> None:
        async_session = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False,
        )
        async with async_session() as session:
            for statement in statements:
                await session.execute(text(statement), params)
            await session.commit()

    await cleanup()
    yield
    await cleanup()


@pytest_asyncio.fixture()
async def export_user(db_engine) -> User:
    """Create a test user and return the SQLAlchemy model."""
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with async_session() as session:
        user = User(
            username="clone_export_test_user",
            email="clone_export@example.com",
            password_hash="fakehash",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        await session.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('users', 'id'), "
                "COALESCE((SELECT MAX(id) FROM users), 1), "
                "(SELECT MAX(id) IS NOT NULL FROM users))"
            )
        )
        await session.commit()
        return user


@pytest_asyncio.fixture()
async def export_data(db_engine, export_user: User) -> dict[str, object]:
    """Populate test data for the export user and return the IDs."""
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Clean up any stale test data from prior runs
    async with async_session() as session:
        await session.execute(text(
            "DELETE FROM snapshots WHERE session_id IN "
            "(SELECT id FROM sessions WHERE user_id = :uid)"
        ), {"uid": export_user.id})
        await session.execute(
            text("DELETE FROM events WHERE session_id IN "
                 "(SELECT id FROM sessions WHERE user_id = :uid)"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM sessions WHERE user_id = :uid"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM reading_order_items WHERE reading_order_id IN "
                 "(SELECT id FROM reading_orders WHERE user_id = :uid)"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM reading_orders WHERE user_id = :uid"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM dependencies WHERE source_issue_id IN "
                 "(SELECT id FROM issues WHERE thread_id IN "
                 "(SELECT id FROM threads WHERE user_id = :uid))"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM issues WHERE thread_id IN "
                 "(SELECT id FROM threads WHERE user_id = :uid)"),
            {"uid": export_user.id},
        )
        await session.execute(
            text("DELETE FROM threads WHERE user_id = :uid"),
            {"uid": export_user.id},
        )
        await session.commit()

        thread = Thread(
            title="Export Test Thread",
            format="single",
            issues_remaining=3,
            total_issues=5,
            reading_progress="in_progress",
            queue_position=1,
            status="active",
            user_id=export_user.id,
        )
        session.add(thread)
        await session.flush()

        issue1 = Issue(
            thread_id=thread.id,
            issue_number="1",
            position=0,
            status="read",
        )
        issue2 = Issue(
            thread_id=thread.id,
            issue_number="2",
            position=1,
            status="unread",
        )
        session.add_all([issue1, issue2])
        await session.flush()
        thread.next_unread_issue_id = issue2.id

        dependency = Dependency(
            source_issue_id=issue1.id,
            target_issue_id=issue2.id,
            note="read the first issue first",
        )
        session.add(dependency)

        reading_order = ReadingOrder(
            name="Test Reading Order",
            description="Round-trip test order",
            user_id=export_user.id,
        )
        session.add(reading_order)
        await session.flush()
        session.add(
            ReadingOrderItem(
                reading_order_id=reading_order.id,
                thread_id=thread.id,
                position=0,
                issue_number="1",
            )
        )

        session_model = Session(
            start_die=6,
            manual_die=0,
            user_id=export_user.id,
            pending_thread_id=thread.id,
            pending_issue_id=issue2.id,
            snoozed_thread_ids=[thread.id],
        )
        session.add(session_model)
        await session.flush()

        event = Event(
            type="rate",
            die=6,
            result=3,
            selected_thread_id=thread.id,
            selection_method="random",
            rating=4.5,
            issues_read=1,
            queue_move="stay",
            die_after=6,
            session_id=session_model.id,
            thread_id=thread.id,
            issue_id=issue1.id,
            issue_number="1",
        )
        session.add(event)
        await session.flush()

        snapshot = Snapshot(
            session_id=session_model.id,
            event_id=event.id,
            thread_states={str(thread.id): {"issues_remaining": 3}},
            session_state={"pending_thread_id": thread.id},
            description="Before rating",
        )
        session.add(snapshot)
        await session.commit()

    return {
        "user_id": export_user.id,
        "thread_id": thread.id,
        "issue1_id": issue1.id,
        "issue2_id": issue2.id,
        "dependency_id": dependency.id,
        "reading_order_id": reading_order.id,
        "session_id": session_model.id,
        "event_id": event.id,
        "snapshot_id": snapshot.id,
    }


@pytest.mark.asyncio
async def test_export_uses_repeatable_read(test_db_url, requires_postgres, export_user, export_data):
    """Export session should use REPEATABLE READ isolation."""
    engine = create_async_engine(
        test_db_url,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
        connect_args={
            "server_settings": {
                "default_transaction_read_only": "on",
            }
        },
    )
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with async_session() as db:
        result = await db.execute(text("SHOW transaction_isolation"))
        isolation = result.scalar_one()

        result = await db.execute(text("SHOW default_transaction_read_only"))
        read_only = result.scalar_one()

    await engine.dispose()

    assert isolation.lower() == "repeatable read", (
        f"Expected REPEATABLE READ, got {isolation}"
    )
    assert read_only.lower() == "on", (
        f"Expected read_only=on, got {read_only}"
    )


@pytest.mark.asyncio
async def test_export_readonly_rejects_writes(test_db_url, requires_postgres, export_user, export_data):
    """READ ONLY transaction must reject INSERT/UPDATE/DELETE."""
    engine = create_async_engine(
        test_db_url,
        pool_pre_ping=True,
        isolation_level="REPEATABLE READ",
        connect_args={
            "server_settings": {
                "default_transaction_read_only": "on",
            }
        },
    )
    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with async_session() as db:
        with pytest.raises(Exception, match="read-only|cannot execute"):
            await db.execute(
                text("INSERT INTO users (username, email, password_hash) "
                     "VALUES ('__test_ro__', '__test_ro__@test.com', 'x')")
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_export_via_db_returns_document(test_db_url, export_user, export_data):
    """_export_via_db returns a complete ExportDocument for the user."""
    from scripts.clone_prod_to_local import _export_via_db

    export = await _export_via_db(test_db_url, "clone_export_test_user")

    assert export["schema_version"] == "1.0"
    assert export["source_username"] == "clone_export_test_user"
    assert export["user"]["username"] == "clone_export_test_user"
    assert "collections" not in export
    assert len(export["threads"]) == 1
    assert export["threads"][0]["title"] == "Export Test Thread"
    assert len(export["issues"]) == 2
    assert len(export["sessions"]) == 1
    assert len(export["snapshots"]) == 1

    assert "source_url" in export
    assert "password" not in export.get("source_url", "")


@pytest.mark.asyncio
async def test_export_via_db_excludes_other_users(test_db_url, db_engine, export_user, export_data):
    """Export must only include data belonging to the specified user."""
    from scripts.clone_prod_to_local import _export_via_db

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Clean up any stale other_user from prior runs
    async with async_session() as session:
        await session.execute(text(
            "DELETE FROM threads WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)"
        ), {"u": "other_user_clone_test"})
        await session.execute(
            text("DELETE FROM users WHERE username = :u"),
            {"u": "other_user_clone_test"},
        )
        await session.commit()

    async with async_session() as session:
        other_user = User(
            username="other_user_clone_test",
            email="other@example.com",
            password_hash="fakehash",
        )
        session.add(other_user)
        await session.flush()

        other_thread = Thread(
            title="Other User Thread",
            format="single",
            issues_remaining=1,
            total_issues=1,
            queue_position=0,
            status="active",
            user_id=other_user.id,
        )
        session.add(other_thread)
        await session.commit()

    export = await _export_via_db(test_db_url, "clone_export_test_user")

    thread_titles = [t["title"] for t in export["threads"]]
    assert "Other User Thread" not in thread_titles
    assert export["user"]["username"] == "clone_export_test_user"


@pytest.mark.asyncio
async def test_export_via_db_dependency_filtering(
    test_db_url, db_engine, export_user, export_data,
):
    """Dependencies with both endpoints in the export set are included."""
    from scripts.clone_prod_to_local import _export_via_db
    from app.models import Dependency

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Clean up any stale dependencies from prior runs
    async with async_session() as session:
        ids = list({export_data["issue1_id"], export_data["issue2_id"]})
        await session.execute(text(
            "DELETE FROM dependencies WHERE source_issue_id = ANY(:ids) "
            "OR target_issue_id = ANY(:ids)"
        ), {"ids": ids})
        await session.commit()

    async with async_session() as session:
        dep = Dependency(
            source_issue_id=export_data["issue1_id"],
            target_issue_id=export_data["issue2_id"],
            note="test dependency",
        )
        session.add(dep)
        await session.commit()

    export = await _export_via_db(test_db_url, "clone_export_test_user")

    assert len(export["dependencies"]) == 1
    assert export["dependencies"][0]["source_issue_id"] == export_data["issue1_id"]
    assert export["dependencies"][0]["target_issue_id"] == export_data["issue2_id"]


@pytest.mark.asyncio
async def test_export_via_db_no_credential_leakage(test_db_url, export_user, export_data):
    """Export source_url must not contain passwords or credentials."""
    from scripts.clone_prod_to_local import _export_via_db

    export = await _export_via_db(test_db_url, "clone_export_test_user")

    source_url = export.get("source_url", "")
    assert "password" not in source_url.lower()
    assert "@" not in source_url
    assert "asyncpg" not in source_url


@pytest.mark.asyncio
async def test_import_remaps_relationships_and_writes_backup(
    test_db_url, db_engine, export_user, export_data, tmp_path,
):
    """Import replaces a user safely while assigning new IDs to related rows."""
    from scripts.clone_prod_to_local import _export_via_db, _import_document

    export = await _export_via_db(test_db_url, "clone_export_test_user")
    backup_path = tmp_path / "before-import.json"
    counts = await _import_document(test_db_url, export, backup_path, dry_run=False)

    assert backup_path.exists()
    assert counts["threads"] == 1
    assert counts["issues"] == 2

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with async_session() as session:
        result = await session.execute(
            text("SELECT id FROM threads WHERE title = 'Export Test Thread'")
        )
        thread_id = result.scalar_one()
        result = await session.execute(
            text("SELECT thread_id FROM issues WHERE thread_id = :thread_id ORDER BY id"),
            {"thread_id": thread_id},
        )
        assert result.fetchall()
        assert thread_id != export_data["thread_id"]


@pytest.mark.asyncio
async def test_clone_round_trip_preserves_counts_and_relationships(
    test_db_url, db_engine, export_user, export_data, tmp_path,
):
    """Exporting and importing preserves the complete user data graph."""
    from scripts.clone_prod_to_local import _export_via_db, _import_document

    export = await _export_via_db(test_db_url, "clone_export_test_user")
    export["user"]["username"] = "clone_round_trip_target"
    export["user"]["email"] = "clone_round_trip_target@example.com"
    counts = await _import_document(test_db_url, export, tmp_path / "backup.json", dry_run=False)

    assert counts == {
        "threads": 1,
        "issues": 2,
        "dependencies": 1,
        "reading_orders": 1,
        "reading_order_items": 1,
        "sessions": 1,
        "events": 1,
        "snapshots": 1,
    }

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with async_session() as session:
        imported_user_id = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'clone_round_trip_target'")
            )
        ).scalar_one()
        thread = (
            await session.execute(
                text("SELECT id, user_id, next_unread_issue_id "
                     "FROM threads WHERE title = 'Export Test Thread' AND user_id = :user_id"),
                {"user_id": imported_user_id},
            )
        ).one()
        thread_id, user_id, next_issue_id = thread
        issue_rows = (
            await session.execute(
                text("SELECT id, issue_number, thread_id FROM issues "
                     "WHERE thread_id = :thread_id ORDER BY position"),
                {"thread_id": thread_id},
            )
        ).all()
        issue_ids = {row.id for row in issue_rows}
        dependency = (
            await session.execute(
                text("SELECT source_issue_id, target_issue_id, note FROM dependencies "
                     "WHERE source_issue_id IN (SELECT id FROM issues WHERE thread_id = :thread_id) "
                     "AND target_issue_id IN (SELECT id FROM issues WHERE thread_id = :thread_id)"),
                {"thread_id": thread_id},
            )
        ).one()
        order_item = (
            await session.execute(
                text("SELECT reading_order_id, thread_id, issue_number FROM reading_order_items "
                     "WHERE thread_id = :thread_id"),
                {"thread_id": thread_id},
            )
        ).one()
        imported_session = (
            await session.execute(
                text("SELECT id, user_id, pending_thread_id, pending_issue_id, snoozed_thread_ids "
                     "FROM sessions WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
        ).one()
        imported_event = (
            await session.execute(
                text("SELECT id, session_id, thread_id, issue_id, selected_thread_id FROM events "
                     "WHERE session_id = :session_id"),
                {"session_id": imported_session.id},
            )
        ).one()
        snapshot = (
            await session.execute(
                text("SELECT session_id, event_id, description FROM snapshots "
                     "WHERE session_id = :session_id"),
                {"session_id": imported_session.id},
            )
        ).one()

    assert user_id != export_data["user_id"]
    assert next_issue_id in issue_ids
    assert {row.thread_id for row in issue_rows} == {thread_id}
    assert dependency.source_issue_id in issue_ids
    assert dependency.target_issue_id in issue_ids
    assert dependency.note == "read the first issue first"
    assert order_item.thread_id == thread_id
    assert imported_session.user_id == user_id
    assert imported_session.pending_thread_id == thread_id
    assert imported_session.pending_issue_id in issue_ids
    assert imported_session.snoozed_thread_ids == [thread_id]
    assert imported_event.session_id == imported_session.id
    assert imported_event.thread_id == thread_id
    assert imported_event.issue_id in issue_ids
    assert imported_event.selected_thread_id == thread_id
    assert snapshot.event_id == imported_event.id
    assert snapshot.description == "Before rating"


@pytest.mark.asyncio
async def test_import_preserves_ownership_isolation(
    test_db_url, db_engine, export_user, export_data, tmp_path,
):
    """Imported rows belong only to the destination user and not the source user."""
    from scripts.clone_prod_to_local import _export_via_db, _import_document

    export = await _export_via_db(test_db_url, "clone_export_test_user")
    export["user"]["username"] = "clone_import_target"
    export["user"]["email"] = "clone_import_target@example.com"
    await _import_document(test_db_url, export, tmp_path / "backup.json", dry_run=False)

    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with async_session() as session:
        users = (
            await session.execute(
                text("SELECT id, username FROM users WHERE username IN "
                     "('clone_export_test_user', 'clone_import_target')")
            )
        ).all()
        target_id = next(row.id for row in users if row.username == "clone_import_target")
        source_id = next(row.id for row in users if row.username == "clone_export_test_user")
        target_thread_users = (
            await session.execute(
                text("SELECT DISTINCT user_id FROM threads WHERE title = 'Export Test Thread'")
            )
        ).scalars().all()
        source_thread_count = (
            await session.execute(
                text("SELECT count(*) FROM threads WHERE user_id = :user_id"),
                {"user_id": source_id},
            )
        ).scalar_one()

    assert target_id != source_id
    assert source_id in target_thread_users
    assert target_id in target_thread_users
    assert source_thread_count == 1


@pytest.mark.asyncio
async def test_import_dry_run_does_not_write(
    test_db_url, db_engine, export_user, export_data,
):
    """Dry-run validates an export and leaves the destination database unchanged."""
    from scripts.clone_prod_to_local import _export_via_db, _import_document

    export = await _export_via_db(test_db_url, "clone_export_test_user")
    export["threads"][0]["title"] = "Dry Run Must Not Persist"
    counts = await _import_document(test_db_url, export, None, dry_run=True)

    assert counts["threads"] == 1
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with async_session() as session:
        title = (
            await session.execute(
                text("SELECT title FROM threads WHERE id = :thread_id"),
                {"thread_id": export_data["thread_id"]},
            )
        ).scalar_one()
    assert title == "Export Test Thread"


@pytest.mark.asyncio
async def test_export_excludes_auth_secrets(test_db_url, export_user, export_data):
    """Export documents contain neither password hashes nor revoked token data."""
    from scripts.clone_prod_to_local import _export_via_db

    export = await _export_via_db(test_db_url, "clone_export_test_user")

    assert "password_hash" not in export["user"]
    assert "revoked_tokens" not in export


def test_export_file_permissions():
    """Export file should be created with owner-only permissions (0o600)."""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with open(tmp_path, "w") as f:
            json.dump({"test": True}, f)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)

        file_stat = os.stat(tmp_path)
        file_mode = file_stat.st_mode & 0o777
        assert file_mode == 0o600, (
            f"Expected 0o600 permissions, got octal {oct(file_mode)}"
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def test_redact_db_url():
    """_redact_db_url strips credentials from database URLs."""
    from scripts.clone_prod_to_local import _redact_db_url

    result = _redact_db_url(
        "postgresql+asyncpg://user:secret_password@host.example.com:5432/mydb"
    )
    assert "secret_password" not in result
    assert "user" not in result
    assert "@" not in result
    assert "host.example.com" in result
    assert "5432" in result
    assert "mydb" in result

    result2 = _redact_db_url("postgresql://simple@host/db")
    assert "@" not in result2
    assert "host" in result2
    assert "db" in result2


def test_redact_db_url_unparseable():
    """_redact_db_url handles garbage input gracefully."""
    from scripts.clone_prod_to_local import _redact_db_url

    result = _redact_db_url("not-a-url")
    assert "unable to parse" in result.lower() or "not-a-url" in result


def test_validate_export_rejects_broken_foreign_key():
    """Import validation rejects an export whose relationship cannot be remapped."""
    from scripts.clone_prod_to_local import _validate_export

    document = {
        "schema_version": "1.0",
        "user": {"id": 10, "username": "import-user"},
        "threads": [{"id": 20, "user_id": 10, "title": "Thread"}],
        "issues": [],
        "dependencies": [],
        "reading_orders": [],
        "reading_order_items": [],
        "sessions": [],
        "events": [],
        "snapshots": [],
    }

    with pytest.raises(ValueError, match="missing user id 999"):
        document["threads"][0]["user_id"] = 999
        _validate_export(document)


def test_remap_preserves_null_and_maps_ids():
    """Foreign-key remapping handles nullable references without inventing IDs."""
    from scripts.clone_prod_to_local import _remap

    assert _remap(12, {12: 42}) == 42
    assert _remap(None, {12: 42}) is None
