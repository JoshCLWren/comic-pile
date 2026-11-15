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
async def test_session_with_legacy_thread_returns_nulls(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session API returns null issue metadata for legacy (non-migrated) threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

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

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["title"] == "Legacy Thread"
    assert active_thread["issues_remaining"] == 5
    assert active_thread["total_issues"] is None
    assert active_thread["reading_progress"] is None
    assert active_thread["issue_id"] is None
    assert active_thread["issue_number"] is None
    assert active_thread["next_issue_id"] is None
    assert active_thread["next_issue_number"] is None


@pytest.mark.asyncio
async def test_session_with_migrated_thread_returns_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session API returns issue metadata for migrated threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Migrated Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 11):
        status = "read" if i < 8 else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status=status,
            position=i,
        )
        async_db.add(issue)
    await async_db.commit()

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).where(Issue.issue_number == "8")
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

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["title"] == "Migrated Thread"
    assert active_thread["issues_remaining"] == 3
    assert active_thread["total_issues"] == 10
    assert active_thread["reading_progress"] == "in_progress"
    assert active_thread["issue_id"] == next_issue.id
    assert active_thread["issue_number"] == "8"
    assert active_thread["next_issue_id"] == next_issue.id
    assert active_thread["next_issue_number"] == "8"


@pytest.mark.asyncio
async def test_current_session_refetch_preserves_issue_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Current session keeps next-issue metadata when the session is refetched."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Hydrated Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=4,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 5):
        async_db.add(
            Issue(
                thread_id=thread.id,
                issue_number=str(i),
                status="read" if i < 3 else "unread",
                position=i,
            )
        )
    await async_db.commit()

    issue_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id, Issue.issue_number == "3")
    )
    next_issue = issue_result.scalar_one()
    thread.next_unread_issue_id = next_issue.id
    await async_db.commit()

    async_db.add(
        Event(
            type="roll",
            die=10,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    await async_db.commit()

    current_response = await auth_client.get("/api/v1/sessions/current/")
    assert current_response.status_code == 200

    current_session = current_response.json()
    assert current_session["id"] == session.id
    assert current_session["active_thread"] is not None
    current_active_thread = current_session["active_thread"]
    _assert_issue_metadata(
        current_active_thread,
        issue_id=next_issue.id,
        issue_number="3",
    )

    refetch_response = await auth_client.get(f"/api/v1/sessions/{current_session['id']}")
    assert refetch_response.status_code == 200

    refetched_session = refetch_response.json()
    assert refetched_session["active_thread"] is not None
    refetched_active_thread = refetched_session["active_thread"]
    _assert_issue_metadata(
        refetched_active_thread,
        issue_id=next_issue.id,
        issue_number="3",
    )


@pytest.mark.asyncio
async def test_current_session_legacy_thread_has_null_issue_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Current session returns null next-issue metadata for legacy threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Legacy Hydration Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    async_db.add(
        Event(
            type="roll",
            die=10,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == session.id
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    _assert_issue_metadata(active_thread, issue_id=None, issue_number=None)


@pytest.mark.asyncio
async def test_current_session_completed_thread_has_null_next_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Current session returns null next-issue metadata for completed threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Completed Hydration Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
        reading_progress="in_progress",
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 4):
        async_db.add(
            Issue(
                thread_id=thread.id,
                issue_number=str(i),
                status="read" if i < 3 else "unread",
                position=i,
            )
        )
    await async_db.commit()

    issue_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id, Issue.issue_number == "3")
    )
    final_issue = issue_result.scalar_one()
    thread.next_unread_issue_id = final_issue.id
    await async_db.commit()

    async_db.add(
        Event(
            type="roll",
            die=10,
            result=1,
            selected_thread_id=thread.id,
            selection_method="random",
            session_id=session.id,
            thread_id=thread.id,
        )
    )

    final_issue.status = "read"
    thread.status = "completed"
    thread.issues_remaining = 0
    thread.reading_progress = "completed"
    thread.next_unread_issue_id = None

    async_db.add(
        Event(
            type="rate",
            session_id=session.id,
            thread_id=thread.id,
            rating=4.0,
            issues_read=1,
            die=10,
            die_after=8,
        )
    )
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == session.id
    # After issue #297 fix, completed threads are removed from active slot
    assert data["active_thread"] is None


@pytest.mark.asyncio
async def test_simplified_migration_endpoint(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Simplified migration endpoint works correctly."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Thread to Migrate",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "5"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 9
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "5"

    await async_db.refresh(thread)
    assert thread.total_issues == 9
    assert thread.reading_progress == "in_progress"
    assert thread.next_unread_issue_id is not None

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()
    assert len(issues) == 9

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]
    assert len(read_issues) == 4
    assert len(unread_issues) == 5
    assert unread_issues[0].issue_number == "5"


@pytest.mark.asyncio
async def test_completed_thread_session_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session API shows correct metadata for completed threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
        total_issues=10,
        reading_progress="completed",
        next_unread_issue_id=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 11):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status="read",
            position=i,
        )
        async_db.add(issue)
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

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.0,
        issues_read=1,
        die=10,
        die_after=8,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    # After issue #297 fix, completed threads are removed from active slot
    assert data["active_thread"] is None


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


@pytest.mark.asyncio
async def test_pending_thread_includes_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Pending thread includes issue metadata."""
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

    session.pending_thread_id = thread.id
    await async_db.commit()

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["total_issues"] == 5
    assert active_thread["reading_progress"] == "in_progress"
    assert active_thread["issue_number"] == "4"
    assert active_thread["next_issue_number"] == "4"


@pytest.mark.asyncio
async def test_migration_with_issue_number_1_starts_from_beginning(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Migration with issue_number=1 marks no issues as read, starts fresh."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "1"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 10
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "1"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 10

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]

    assert len(read_issues) == 0
    assert len(unread_issues) == 10
    assert unread_issues[0].issue_number == "1"


@pytest.mark.asyncio
async def test_completed_migrated_thread_has_no_next_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Completed migrated thread returns nulls for issue fields in session."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="completed",
        user_id=user.id,
        total_issues=10,
        reading_progress="completed",
        next_unread_issue_id=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    for i in range(1, 11):
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(i),
            status="read",
            position=i,
        )
        async_db.add(issue)
    await async_db.commit()

    event = Event(
        type="rate",
        session_id=session.id,
        thread_id=thread.id,
        rating=4.0,
        issues_read=1,
        die=10,
        die_after=8,
    )
    async_db.add(event)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    # After issue #297 fix, completed threads are removed from active slot
    assert data["active_thread"] is None


@pytest.mark.asyncio
async def test_legacy_thread_returns_nulls_for_issue_fields(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Legacy thread (not migrated) returns nulls for issue metadata."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = ReadingSession(start_die=10, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Legacy Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

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

    response = await auth_client.get(f"/api/v1/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["issues_remaining"] == 5
    assert active_thread["total_issues"] is None
    assert active_thread["reading_progress"] is None
    assert active_thread["issue_id"] is None
    assert active_thread["issue_number"] is None
    assert active_thread["next_issue_id"] is None
    assert active_thread["next_issue_number"] is None


@pytest.mark.asyncio
async def test_simple_migration_creates_correct_issues(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """MigrateToIssuesSimple must not create a phantom extra issue.

    Regression test for the off-by-one bug in thread.py:833:
        total_issues = thread.issues_remaining + issue_number
    should be:
        total_issues = thread.issues_remaining + issue_number - 1

    Scenario: thread has 5 issues remaining, user just read issue #1.
    Correct total = 5 + 1 - 1 = 5, so migration creates 5 unread issues.
    Buggy code produces 6, leaving a phantom issue that blocks completion.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Simple Migration Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=None,
        next_unread_issue_id=None,
        reading_progress=None,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": "1"}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 5, (
        "total_issues should be issues_remaining + issue_number - 1 = 5, "
        f"got {data['total_issues']} (off-by-one bug produces 6)"
    )
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "1"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 5, (
        f"Expected 5 issues, got {len(issues)} — phantom issue created by off-by-one bug"
    )

    unread_issues = [i for i in issues if i.status == "unread"]
    read_issues = [i for i in issues if i.status == "read"]

    assert len(unread_issues) == 5
    assert len(read_issues) == 0
    assert unread_issues[0].issue_number == "1"
    assert unread_issues[-1].issue_number == "5"

