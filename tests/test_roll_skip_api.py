"""Tests for roll skip endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_skip_advances_to_different_result(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/skip advances pending to a different eligible thread."""
    _ = sample_data
    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200
    first_thread_id = roll_response.json()["thread_id"]

    skip_response = await auth_client.post("/api/v1/roll/skip")
    assert skip_response.status_code == 200
    data = skip_response.json()
    assert data["thread_id"] != first_thread_id
    assert data["die_size"] >= 1

    session_response = await auth_client.get("/api/v1/sessions/current/")
    assert session_response.json()["pending_thread_id"] == data["thread_id"]


@pytest.mark.asyncio
async def test_skip_leaves_skipped_issue_history_unchanged(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Skipping must not mark issue read or change read_at/ratings."""
    from app.models import Issue, Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread_a = Thread(
        title="Skip A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_rating=None,
    )
    thread_b = Thread(
        title="Skip B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([thread_a, thread_b])
    await async_db.flush()
    issue_a = Issue(
        thread_id=thread_a.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    issue_b = Issue(
        thread_id=thread_b.id,
        issue_number="1",
        status="unread",
        position=1,
    )
    async_db.add_all([issue_a, issue_b])
    await async_db.commit()
    await async_db.refresh(thread_a)
    await async_db.refresh(issue_a)

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200
    skipped_thread_id = roll_response.json()["thread_id"]
    # Capture skipped issue state
    skipped_issue_id = roll_response.json().get("issue_id")
    if skipped_issue_id:
        before_issue = await async_db.get(Issue, skipped_issue_id)
        assert before_issue is not None
        before_status = before_issue.status
        before_read_at = before_issue.read_at
    else:
        before_status = None
        before_read_at = None

    before_thread = await async_db.get(Thread, skipped_thread_id)
    assert before_thread is not None
    before_rating = before_thread.last_rating

    skip_response = await auth_client.post("/api/v1/roll/skip")
    assert skip_response.status_code == 200

    # Verify skipped thread unchanged
    await async_db.refresh(before_thread)
    assert before_thread.last_rating == before_rating
    if skipped_issue_id:
        after_issue = await async_db.get(Issue, skipped_issue_id)
        assert after_issue is not None
        assert after_issue.status == before_status
        assert after_issue.read_at == before_read_at


@pytest.mark.asyncio
async def test_skip_without_pending_returns_409(auth_client: AsyncClient, sample_data: dict) -> None:
    """Skip without pending roll returns 409."""
    _ = sample_data
    # Ensure no pending
    await auth_client.post("/api/v1/roll/dismiss-pending")
    response = await auth_client.post("/api/v1/roll/skip")
    assert response.status_code == 409
    assert "No pending roll" in response.json()["detail"]


@pytest.mark.asyncio
async def test_skip_no_alternative_returns_400(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Skip returns 400 when no alternative threads available."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200

    skip_response = await auth_client.post("/api/v1/roll/skip")
    assert skip_response.status_code == 400
    assert "No alternative" in skip_response.json()["detail"]


@pytest.mark.asyncio
async def test_skip_respects_blocked_governance(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Skip must not select blocked threads."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    t1 = Thread(title="T1", format="Comic", issues_remaining=1, queue_position=1, status="active", user_id=user.id, is_blocked=False)
    t2 = Thread(title="T2 Blocked", format="Comic", issues_remaining=1, queue_position=2, status="active", user_id=user.id, is_blocked=True)
    t3 = Thread(title="T3", format="Comic", issues_remaining=1, queue_position=3, status="active", user_id=user.id, is_blocked=False)
    async_db.add_all([t1, t2, t3])
    await async_db.commit()

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200

    # Skip enough times that blocked would be candidate if not filtered; ensure never returns blocked
    for _ in range(3):
        # Dismiss and roll again if needed to get pending change? For this test just verify skip doesn't return blocked
        skip_response = await auth_client.post("/api/v1/roll/skip")
        if skip_response.status_code == 200:
            assert skip_response.json()["thread_id"] != t2.id
            break
        # If no alternative, dismissed path not needed
        await auth_client.post("/api/v1/roll/dismiss-pending")
        roll_response = await auth_client.post("/api/v1/roll/")
        assert roll_response.status_code == 200
