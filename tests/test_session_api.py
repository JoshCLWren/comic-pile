"""Tests for session API with issue metadata."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models import ReadingSession


def _assert_issue_metadata(
    active_thread: dict[str, object],
    *,
    issue_id: int | None,
    issue_number: str | None,
) -> None:
    assert active_thread["issue_id"] == issue_id
    assert active_thread["issue_number"] == issue_number
    assert active_thread["next_issue_id"] == issue_id
    assert active_thread["next_issue_number"] == issue_number




@pytest.mark.asyncio
async def test_session_list_with_migrated_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session list endpoint includes issue metadata."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Migrated Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 6):
        status = "read" if i < 4 else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status=status,
            position=i,
        )
        async_db.add(issue)
    await async_db.commit()

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).where(Issue.issue_number == "4")
    )
    next_issue = result.scalar_one()
    thread.next_unread_issue_id = next_issue.id
    await async_db.commit()

    event = Event(
        type="roll",
        die=10,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/")
    assert response.status_code == 200

    data = response.json()
    assert "sessions" in data
    sessions = data["sessions"]
    assert len(sessions) >= 1
    session_data = next(s for s in sessions if s["id"] == session.id)
    assert session_data["active_thread"] is not None
    active_thread = session_data["active_thread"]
    assert active_thread["total_issues"] == 5
    assert active_thread["reading_progress"] == "in_progress"
    assert active_thread["issue_number"] == "4"




