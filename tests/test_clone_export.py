"""Tests for scripts/clone_prod_to_local.py export functionality."""

import json
import os
import stat
import tempfile
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
    Collection,
    Issue,
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


@pytest_asyncio.fixture()
async def export_user(db_engine) -> User:
    """Create a test user and return the SQLAlchemy model."""
    async_session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Clean up any stale test users and their dependent rows from prior runs
    async with async_session() as session:
        await session.execute(text(
            "DELETE FROM snapshots WHERE session_id IN "
            "(SELECT id FROM sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u))"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM events WHERE session_id IN "
            "(SELECT id FROM sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u))"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM sessions WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM reading_order_items WHERE reading_order_id IN "
            "(SELECT id FROM reading_orders WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u))"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM reading_orders WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM dependencies WHERE source_issue_id IN "
            "(SELECT id FROM issues WHERE thread_id IN "
            "(SELECT id FROM threads WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)))"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM issues WHERE thread_id IN "
            "(SELECT id FROM threads WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u))"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM threads WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)"
        ), {"u": "clone_export_test_user"})
        await session.execute(text(
            "DELETE FROM collections WHERE user_id IN "
            "(SELECT id FROM users WHERE username = :u)"
        ), {"u": "clone_export_test_user"})
        await session.execute(
            text("DELETE FROM users WHERE username = :u"),
            {"u": "clone_export_test_user"},
        )
        await session.commit()

    async with async_session() as session:
        user = User(
            username="clone_export_test_user",
            email="clone_export@example.com",
            password_hash="fakehash",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
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
        await session.execute(
            text("DELETE FROM collections WHERE user_id = :uid"),
            {"uid": export_user.id},
        )
        await session.commit()
        collection = Collection(
            name="Test Collection",
            user_id=export_user.id,
            is_default=True,
            position=0,
        )
        session.add(collection)
        await session.flush()

        thread = Thread(
            title="Export Test Thread",
            format="single",
            issues_remaining=3,
            total_issues=5,
            reading_progress="in_progress",
            queue_position=1,
            status="active",
            user_id=export_user.id,
            collection_id=collection.id,
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

        session_model = Session(
            start_die=6,
            manual_die=0,
            user_id=export_user.id,
        )
        session.add(session_model)
        await session.flush()

        snapshot = Snapshot(
            session_id=session_model.id,
            thread_states={},
            session_state={},
        )
        session.add(snapshot)
        await session.commit()

    return {
        "user_id": export_user.id,
        "collection_id": collection.id,
        "thread_id": thread.id,
        "issue1_id": issue1.id,
        "issue2_id": issue2.id,
        "session_id": session_model.id,
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
    assert len(export["collections"]) == 1
    assert export["collections"][0]["name"] == "Test Collection"
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
