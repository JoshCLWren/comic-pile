"""Query-count evidence for the bounded Queue response contract."""

from collections import namedtuple
from datetime import UTC, datetime
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.api.thread import list_threads
from app.models import Thread

IssueNumberRow = namedtuple("IssueNumberRow", ["id", "issue_number"])


def _thread(thread_id: int) -> Thread:
    """Build a representative migrated thread without persisting it."""
    return Thread(
        id=thread_id,
        user_id=1,
        title=f"Thread {thread_id}",
        format="Comic",
        issues_remaining=1,
        total_issues=2,
        next_unread_issue_id=10_000 + thread_id,
        reading_progress="in_progress",
        queue_position=thread_id,
        status="active",
        last_rating=None,
        last_activity_at=None,
        notes=None,
        is_test=False,
        is_blocked=False,
        created_at=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _result(*, scalars: list[Thread] | None = None, rows: list[object] | None = None) -> MagicMock:
    """Return a minimal SQLAlchemy result double for route-level query evidence."""
    result = MagicMock()
    if scalars is not None:
        result.scalars.return_value.all.return_value = scalars
    if rows is not None:
        result.__iter__.return_value = iter(rows)
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_count", [1, 50])
async def test_queue_query_count_is_constant_for_page_size(thread_count: int) -> None:
    """Queue construction uses three SQL executions regardless of returned rows."""
    threads = [_thread(thread_id) for thread_id in range(1, thread_count + 1)]
    issue_rows = [
        IssueNumberRow(thread.next_unread_issue_id, str(thread.id + 1))
        for thread in threads
    ]
    remaining_rows = [(thread.id, 1) for thread in threads]

    db = AsyncMock()
    db.execute.side_effect = [
        _result(scalars=threads),
        _result(rows=issue_rows),
        _result(rows=remaining_rows),
    ]
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/threads/",
            "headers": [],
            "query_string": b"",
        }
    )

    route = unwrap(list_threads)
    response = await route(
        request=request,
        current_user=SimpleNamespace(id=1),
        db=db,
        search=None,
        page_size=thread_count,
        page_token=None,
    )

    assert len(response.threads) == thread_count
    assert db.execute.await_count == 3
