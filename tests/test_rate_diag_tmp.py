"""Temporary diagnostics for issue #3389 (deleted before commit)."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread


@contextmanager
def _capture(db_engine: AsyncEngine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _before)


@pytest.mark.asyncio
async def test_rate_query_diagnosis(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print every statement executed during a rate request on issue-tracked threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    for index in range(1, 51):
        thread = Thread(
            title=f"Thread {index}",
            format="Comic",
            issues_remaining=10,
            total_issues=10,
            reading_progress="in_progress",
            queue_position=index,
            status="active",
            user_id=user.id,
        )
        async_db.add(thread)
        await async_db.flush()
        issues = []
        for position in range(1, 11):
            issue = Issue(
                thread_id=thread.id,
                issue_number=str(position),
                status="read" if position < 3 else "unread",
                position=position,
            )
            async_db.add(issue)
            issues.append(issue)
        await async_db.flush()
        thread.next_unread_issue_id = issues[2].id
    await async_db.commit()

    roll_resp = await auth_client.post("/api/v1/roll/")
    assert roll_resp.status_code == 200

    with _capture(db_engine) as statements:
        rate_resp = await auth_client.post("/api/v1/rate/", json={"rating": 3.0})
    assert rate_resp.status_code == 200

    with capsys.disabled():
        print(f"\n=== RATE STATEMENTS: {len(statements)} ===")
        for index, statement in enumerate(statements, start=1):
            print(f"{index:02d}. {statement[:220]}")

    assert False, "diagnostic run"
