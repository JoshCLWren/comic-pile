"""Tests for session API with issue metadata."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event, Issue, Thread
from app.models import Session as SessionModel


@pytest.mark.asyncio
async def test_session_with_legacy_thread_returns_nulls(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session API returns null issue metadata for legacy (non-migrated) threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get(f"/api/sessions/{session.id}")
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

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get(f"/api/sessions/{session.id}")
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
        f"/api/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": 5}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 10
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "5"

    await async_db.refresh(thread)
    assert thread.total_issues == 10
    assert thread.reading_progress == "in_progress"
    assert thread.next_unread_issue_id is not None

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()
    assert len(issues) == 10

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]
    assert len(read_issues) == 4
    assert len(unread_issues) == 6
    assert unread_issues[0].issue_number == "5"


@pytest.mark.asyncio
async def test_rate_with_issue_number_triggers_migration(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Rating with issue_number triggers automatic migration."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issue_number": 6})
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 11
    assert data["reading_progress"] == "in_progress"
    assert data["issues_remaining"] == 5

    await async_db.refresh(thread)
    assert thread.total_issues == 11
    assert thread.reading_progress == "in_progress"

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()
    assert len(issues) == 11

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 6


@pytest.mark.asyncio
async def test_completed_thread_session_metadata(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session API shows correct metadata for completed threads."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["issues_remaining"] == 0
    assert active_thread["total_issues"] == 10
    assert active_thread["reading_progress"] == "completed"
    assert active_thread["issue_id"] is None
    assert active_thread["issue_number"] is None
    assert active_thread["next_issue_id"] is None
    assert active_thread["next_issue_number"] is None


@pytest.mark.asyncio
async def test_session_list_with_migrated_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Session list endpoint includes issue metadata."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get("/api/sessions/")
    assert response.status_code == 200

    sessions = response.json()
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

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get("/api/sessions/current/")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["total_issues"] == 5
    assert active_thread["reading_progress"] == "in_progress"
    assert active_thread["issue_number"] == "4"
    assert active_thread["next_issue_number"] == "4"


@pytest.mark.asyncio
async def test_migration_during_rating_marks_issues_correctly(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Rating with issue_number triggers migration and marks issues correctly."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.post("/api/rate/", json={"rating": 4.0, "issue_number": 8})
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 13
    assert data["reading_progress"] == "in_progress"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 13

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]

    assert len(read_issues) == 8
    assert len(unread_issues) == 5

    assert read_issues[0].issue_number == "1"
    assert read_issues[-1].issue_number == "8"
    assert unread_issues[0].issue_number == "9"


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
        f"/api/threads/{thread.id}:migrateToIssuesSimple", json={"issue_number": 1}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 11
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_number"] == "1"

    await async_db.refresh(thread)

    issues_result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread.id).order_by(Issue.position)
    )
    issues = issues_result.scalars().all()

    assert len(issues) == 11

    read_issues = [i for i in issues if i.status == "read"]
    unread_issues = [i for i in issues if i.status == "unread"]

    assert len(read_issues) == 0
    assert len(unread_issues) == 11
    assert unread_issues[0].issue_number == "1"


@pytest.mark.asyncio
async def test_completed_migrated_thread_has_no_next_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Completed migrated thread returns nulls for issue fields in session."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get(f"/api/sessions/{session.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["active_thread"] is not None
    active_thread = data["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["total_issues"] == 10
    assert active_thread["reading_progress"] == "completed"
    assert active_thread["issue_id"] is None
    assert active_thread["issue_number"] is None
    assert active_thread["next_issue_id"] is None
    assert active_thread["next_issue_number"] is None


@pytest.mark.asyncio
async def test_legacy_thread_returns_nulls_for_issue_fields(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Legacy thread (not migrated) returns nulls for issue metadata."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    session = SessionModel(start_die=10, user_id=user.id)
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

    response = await auth_client.get(f"/api/sessions/{session.id}")
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
