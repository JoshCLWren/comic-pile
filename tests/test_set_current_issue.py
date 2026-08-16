"""Tests for atomically setting the current issue of a thread (issue #1111)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Session, Thread
from tests.conftest import get_or_create_user_async


async def _build_thread_with_issues(
    async_db: AsyncSession,
    *,
    read_count: int = 0,
    total: int = 20,
) -> tuple[object, Thread, list[Issue]]:
    """Create a migrated thread with ``total`` issues, the first ``read_count`` read."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Black Panther",
        format="Comic",
        issues_remaining=total - read_count,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=total,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    now = datetime.now(UTC)
    issues = []
    for position in range(1, total + 1):
        status = "read" if position <= read_count else "unread"
        read_at = now if status == "read" else None
        issue = Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status=status,
            read_at=read_at,
        )
        async_db.add(issue)
        issues.append(issue)
    await async_db.flush()

    thread.next_unread_issue_id = issues[read_count].id if read_count < total else None
    if read_count == total:
        thread.status = "completed"
        thread.reading_progress = "completed"
        thread.issues_remaining = 0
    await async_db.commit()

    return user, thread, issues


async def _issue_rows(async_db: AsyncSession, thread_id: int) -> list[Issue]:
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position, Issue.id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_set_current_issue_forward_correction(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Correcting #18 → #20 marks #18/#19 read and #20 current in one operation."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=17, total=20)
    target = issues[19]

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": target.id},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["next_unread_issue_id"] == target.id
    assert data["next_unread_issue_number"] == "20"
    assert data["issues_remaining"] == 1
    assert data["reading_progress"] == "in_progress"
    assert data["status"] == "active"

    all_issues = await _issue_rows(async_db, thread.id)
    assert all(issue.status == "read" for issue in all_issues[:19])
    assert all_issues[17].status == "read"
    assert all_issues[17].read_at is not None
    assert all_issues[18].status == "read"
    assert all_issues[19].status == "unread"
    assert all_issues[19].read_at is None
    assert all_issues[0].read_at is not None

    session_result = await async_db.execute(select(Session).where(Session.user_id == user.id))
    session = session_result.scalar_one()
    assert session.pending_thread_id == thread.id
    assert session.pending_issue_id == target.id


@pytest.mark.asyncio
async def test_set_current_issue_backward_correction_is_deterministic(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Moving from #20 back to #18 clears read state at/after the target."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=19, total=20)
    target = issues[17]

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": target.id},
    )
    assert response.status_code == 200

    data = response.json()
    assert data["next_unread_issue_number"] == "18"
    assert data["issues_remaining"] == 3

    all_issues = await _issue_rows(async_db, thread.id)
    assert all(issue.status == "read" for issue in all_issues[:17])
    assert all(issue.status == "unread" for issue in all_issues[17:])
    assert all(issue.read_at is None for issue in all_issues[17:])

    session_result = await async_db.execute(select(Session).where(Session.user_id == user.id))
    session = session_result.scalar_one()
    assert session.pending_issue_id == target.id


@pytest.mark.asyncio
async def test_set_current_issue_preserves_active_roll_selection(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """An active roll for the corrected thread keeps its thread selection."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=17, total=20)
    session = Session(user_id=user.id, start_die=6, pending_thread_id=thread.id)
    async_db.add(session)
    await async_db.commit()

    target = issues[19]
    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": target.id},
    )
    assert response.status_code == 200

    await async_db.refresh(session)
    assert session.pending_thread_id == thread.id
    assert session.pending_issue_id == target.id


@pytest.mark.asyncio
async def test_bootstrap_honors_corrected_pending_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The Roll bootstrap surfaces the corrected issue for the active roll."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=17, total=20)
    session = Session(user_id=user.id, start_die=6, pending_thread_id=thread.id)
    async_db.add(session)
    await async_db.commit()

    target = issues[19]
    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": target.id},
    )
    assert response.status_code == 200

    bootstrap = await auth_client.get("/api/v1/roll/bootstrap")
    assert bootstrap.status_code == 200
    active_thread = bootstrap.json()["active_thread"]
    assert active_thread["id"] == thread.id
    assert active_thread["issue_number"] == "20"
    assert active_thread["next_issue_number"] == "20"


@pytest.mark.asyncio
async def test_set_current_issue_rejects_non_issue_tracking_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Counter-based threads cannot use the atomic correction endpoint."""
    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Legacy",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": 999},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_set_current_issue_rejects_issue_from_other_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Issues that do not belong to the thread are rejected without state changes."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=17, total=20)
    other_thread = Thread(
        title="Other",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(other_thread)
    await async_db.flush()
    foreign_issue = Issue(
        thread_id=other_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add(foreign_issue)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": foreign_issue.id},
    )
    assert response.status_code == 400

    all_issues = await _issue_rows(async_db, thread.id)
    assert all_issues[17].status == "unread"
    assert all_issues[18].status == "unread"
    await async_db.refresh(thread)
    assert thread.next_unread_issue_id == issues[17].id


@pytest.mark.asyncio
async def test_set_current_issue_rejects_unowned_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Another user's thread returns 404."""
    user = await get_or_create_user_async(async_db, username="other_user_1111")
    thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": 1},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_current_issue_requires_valid_issue_id(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The request body must include a positive issue_id."""
    user, thread, issues = await _build_thread_with_issues(async_db, read_count=17, total=20)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/set-current-issue",
        json={"issue_id": 0},
    )
    assert response.status_code == 422

    response = await auth_client.post(f"/api/v1/threads/{thread.id}/set-current-issue", json={})
    assert response.status_code == 422