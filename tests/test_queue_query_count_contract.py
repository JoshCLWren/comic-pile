"""Query-count evidence for the bounded Queue response contract."""

from datetime import UTC, datetime
from inspect import unwrap
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from starlette.requests import Request

from app.api.thread import list_threads
from app.models import Issue, Thread
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_count", [1, 50])
async def test_queue_query_count_is_constant_for_page_size(
    thread_count: int,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Queue construction hydrates every row with three PostgreSQL reads."""
    user = await get_or_create_user_async(async_db)
    expected: dict[int, tuple[str, int]] = {}

    for queue_position in range(1, thread_count + 1):
        thread = Thread(
            user_id=user.id,
            title=f"Thread {queue_position}",
            format="Comic",
            issues_remaining=99,
            total_issues=2,
            reading_progress="in_progress",
            queue_position=queue_position,
            status="active",
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        await async_db.flush()

        first_unread = Issue(
            thread_id=thread.id,
            issue_number=str(queue_position + 1),
            position=1,
            status="unread",
        )
        second_unread = Issue(
            thread_id=thread.id,
            issue_number=f"{queue_position + 1}.1",
            position=2,
            status="unread",
        )
        async_db.add_all([first_unread, second_unread])
        await async_db.flush()

        thread.next_unread_issue_id = first_unread.id
        expected[thread.id] = (first_unread.issue_number, 2)

    await async_db.commit()

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/threads/",
            "headers": [],
            "query_string": b"",
        }
    )
    select_statements: list[str] = []

    def _capture_statement(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        normalized_statement = statement.lstrip().upper()
        if normalized_statement.startswith("SELECT"):
            select_statements.append(statement)

    route = unwrap(list_threads)
    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture_statement)
    try:
        response = await route(
            request=request,
            current_user=SimpleNamespace(id=user.id),
            db=async_db,
            search=None,
            page_size=thread_count,
            page_token=None,
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture_statement)

    assert len(response.threads) == thread_count
    assert len(select_statements) == 3, select_statements

    for queue_thread in response.threads:
        expected_issue_number, expected_remaining = expected[queue_thread.id]
        assert queue_thread.next_unread_issue_number == expected_issue_number
        assert queue_thread.issues_remaining == expected_remaining
