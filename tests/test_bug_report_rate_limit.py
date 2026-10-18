"""Closure-critical tests for the non-admin GitHub issue submission limit (#3074).

Covers: first submission succeeds, the second submission inside the rolling
hour is blocked with a 429/Retry-After contract, submissions after the window
succeed, admins bypass the limit, failed GitHub attempts do not consume the
allowance, the key is the authenticated user identity (not IP), concurrent
submissions cannot bypass the limit, and the durable table migration keeps a
single Alembic head.
"""

from __future__ import annotations

import asyncio
import importlib.util
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth import create_access_token
from app.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, generate_csrf_token
from app.database import get_db
from app.main import app
from app.models import User
from app.models.github_issue_submission_limit import GithubIssueSubmissionLimit
from app.services.github_issue_rate_limit import (
    GithubIssueSubmissionRateLimitError,
    submit_github_issue,
)
from tests.conftest import _create_async_db_override

ISSUE_URL = "https://github.com/test/repo/issues/1"
MIGRATION_ID = "c30740000001"
MIGRATION_PARENT = "p322700000001"


def _payload(title: str = "Test Bug", description: str = "Test description") -> dict[str, str]:
    """Build a minimal bug-report request body."""
    return {"title": title, "description": description}


@contextmanager
def _configured_github() -> Iterator[AsyncMock]:
    """Patch GitHub as configured and return the mocked issue creator."""
    settings = MagicMock()
    settings.is_configured = True
    with (
        patch("app.api.bug_report.get_github_settings", return_value=settings),
        patch(
            "app.services.github_issue_rate_limit.create_bug_report_issue",
            new_callable=AsyncMock,
        ) as mock_create,
    ):
        mock_create.return_value = ISSUE_URL
        yield mock_create


async def _client_for_user(async_db: AsyncSession, username: str, *, is_admin: bool) -> AsyncClient:
    """Create an authenticated client for a freshly created user."""
    user = User(username=username, is_admin=is_admin, created_at=datetime.now(UTC))
    async_db.add(user)
    await async_db.commit()
    await async_db.refresh(user)

    app.dependency_overrides[get_db] = await _create_async_db_override(async_db)
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://test")
    csrf_token = generate_csrf_token()
    ac.cookies.set(CSRF_COOKIE_NAME, csrf_token)
    ac.headers.update({CSRF_HEADER_NAME: csrf_token})
    token = create_access_token(data={"sub": user.username, "jti": "test"})
    ac.headers.update({"Authorization": f"Bearer {token}"})
    return ac


@pytest_asyncio.fixture(scope="function")
async def admin_client(async_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Authenticated admin client; admin bypasses the submission limit."""
    async with await _client_for_user(
        async_db, "rate_limit_admin", is_admin=True
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def second_user_client(async_db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """Authenticated second non-admin client for per-user key verification."""
    async with await _client_for_user(
        async_db, "rate_limit_second_user", is_admin=False
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_first_submission_succeeds_and_records_allowance(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A non-admin's first submission succeeds and consumes the allowance."""
    with _configured_github() as mock_create:
        response = await auth_client.post("/api/bug-reports/", json=_payload())

    assert response.status_code == 201
    assert response.json()["issue_url"] == ISSUE_URL
    assert mock_create.await_count == 1

    limit = (
        await async_db.execute(
            select(GithubIssueSubmissionLimit).where(
                GithubIssueSubmissionLimit.user_id == default_user.id
            )
        )
    ).scalar_one()
    assert limit.last_submitted_at is not None


@pytest.mark.asyncio
async def test_second_submission_within_hour_is_blocked(
    auth_client: AsyncClient,
) -> None:
    """A non-admin's second submission inside the hour returns 429 and no issue."""
    with _configured_github() as mock_create:
        first = await auth_client.post("/api/bug-reports/", json=_payload("First"))
        second = await auth_client.post("/api/bug-reports/", json=_payload("Second"))

    assert first.status_code == 201
    assert second.status_code == 429
    assert mock_create.await_count == 1

    retry_after = second.headers.get("Retry-After")
    assert retry_after is not None
    assert 0 < int(retry_after) <= 3600
    assert second.headers.get("X-RateLimit-Reset") is not None
    detail = second.json()["detail"]
    assert "one GitHub issue per hour" in detail
    assert "Try again" in detail


@pytest.mark.asyncio
async def test_submission_allowed_after_window(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    default_user: User,
) -> None:
    """A submission after the rolling hour succeeds."""
    await async_db.execute(
        insert(GithubIssueSubmissionLimit).values(
            user_id=default_user.id,
            last_submitted_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    await async_db.commit()

    with _configured_github() as mock_create:
        response = await auth_client.post("/api/bug-reports/", json=_payload())

    assert response.status_code == 201
    assert mock_create.await_count == 1


@pytest.mark.asyncio
async def test_admin_bypasses_limit(admin_client: AsyncClient) -> None:
    """Admins can submit repeatedly without consuming an allowance."""
    with _configured_github() as mock_create:
        first = await admin_client.post("/api/bug-reports/", json=_payload("Admin one"))
        second = await admin_client.post("/api/bug-reports/", json=_payload("Admin two"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_failed_github_attempt_does_not_consume_allowance(
    auth_client: AsyncClient,
) -> None:
    """A failed GitHub attempt returns 502 and leaves the hour available."""
    settings = MagicMock()
    settings.is_configured = True
    with (
        patch("app.api.bug_report.get_github_settings", return_value=settings),
        patch(
            "app.services.github_issue_rate_limit.create_bug_report_issue",
            new_callable=AsyncMock,
        ) as failing_create,
    ):
        failing_create.side_effect = RuntimeError("GitHub unavailable")
        failed = await auth_client.post("/api/bug-reports/", json=_payload("Fails"))

    assert failed.status_code == 502

    with _configured_github() as succeeding_create:
        retried = await auth_client.post("/api/bug-reports/", json=_payload("Retry"))

    assert retried.status_code == 201
    assert succeeding_create.await_count == 1


@pytest.mark.asyncio
async def test_limit_key_is_authenticated_user(
    auth_client: AsyncClient,
    second_user_client: AsyncClient,
) -> None:
    """One user's submission never blocks a different authenticated user."""
    with _configured_github() as mock_create:
        first_user = await auth_client.post("/api/bug-reports/", json=_payload("User one"))
        second_user = await second_user_client.post(
            "/api/bug-reports/", json=_payload("User two")
        )

    assert first_user.status_code == 201
    assert second_user.status_code == 201
    assert mock_create.await_count == 2


@pytest.mark.asyncio
async def test_concurrent_submissions_cannot_bypass_limit(db_engine: AsyncEngine) -> None:
    """Two concurrent submissions from one user create exactly one issue."""
    session_maker = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )

    async with session_maker() as setup:
        user = User(username="rate_limit_concurrent", created_at=datetime.now(UTC))
        setup.add(user)
        await setup.commit()
        await setup.refresh(user)
        user_id = user.id

    created_titles: list[str] = []

    async def slow_create(**kwargs: object) -> str:
        created_titles.append(str(kwargs["title"]))
        await asyncio.sleep(0.2)
        return ISSUE_URL

    async def attempt(title: str) -> str:
        async with session_maker() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await submit_github_issue(
                db,
                user=user,
                report_type="bug",
                title=title,
                description="concurrent",
            )

    with patch(
        "app.services.github_issue_rate_limit.create_bug_report_issue",
        new_callable=AsyncMock,
        side_effect=slow_create,
    ):
        results = await asyncio.gather(
            attempt("first"), attempt("second"), return_exceptions=True
        )

    successes = [result for result in results if isinstance(result, str)]
    limited = [
        result for result in results if isinstance(result, GithubIssueSubmissionRateLimitError)
    ]
    assert len(successes) == 1
    assert len(limited) == 1
    assert len(created_titles) == 1

    # A separate connection sees the committed allowance, proving the limit
    # state is durable rather than process-local.
    async with session_maker() as verify:
        stored = await verify.get(GithubIssueSubmissionLimit, user_id)
        assert stored is not None
        assert stored.last_submitted_at is not None

    async with session_maker() as cleanup:
        await cleanup.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await cleanup.commit()


def _migration_path() -> Path:
    """Return the migration script for the submission-limit table."""
    return (
        Path(__file__).parents[1]
        / f"alembic/versions/{MIGRATION_ID}_github_issue_submission_limits.py"
    )


def test_rate_limit_migration_keeps_single_head() -> None:
    """The submission-limit migration extends the graph without forking a head."""
    root = Path(__file__).parents[1]
    script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
    assert len(script.get_heads()) == 1
    revision = script.get_revision(MIGRATION_ID)
    assert revision is not None
    assert revision.down_revision == MIGRATION_PARENT


@pytest.mark.asyncio
async def test_rate_limit_migration_roundtrip_postgres(async_db: AsyncSession) -> None:
    """Upgrade, enforce the FK/PK contract, then downgrade in PostgreSQL."""
    spec = importlib.util.spec_from_file_location("rate_limit_migration", _migration_path())
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def verify(conn: Connection) -> None:
        conn.execute(text("SET LOCAL search_path TO pg_temp, public"))
        conn.execute(text("CREATE TEMP TABLE users (id integer PRIMARY KEY) ON COMMIT DROP"))
        conn.execute(text("INSERT INTO users (id) VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()

        conn.execute(
            text(
                "INSERT INTO github_issue_submission_limits (user_id, last_submitted_at) "
                "VALUES (1, now())"
            )
        )
        # Primary key rejects a second row for the same user.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("INSERT INTO github_issue_submission_limits (user_id) VALUES (1)")
            )
        # Foreign key rejects a row for a user that does not exist.
        with pytest.raises(IntegrityError), conn.begin_nested():
            conn.execute(
                text("INSERT INTO github_issue_submission_limits (user_id) VALUES (99)")
            )
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
        assert (
            conn.execute(
                text("SELECT to_regclass('pg_temp.github_issue_submission_limits')")
            ).scalar_one()
            is None
        )

    connection = await async_db.connection()
    await connection.run_sync(verify)
