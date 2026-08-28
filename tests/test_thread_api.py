"""Tests for Thread API endpoints."""

import pytest
from datetime import UTC, datetime, timedelta
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from tests.conftest import get_or_create_user_async


@pytest.mark.asyncio
async def test_reactivate_thread_uses_max_numeric_issue_number(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Reactivation appends regular issue numbers after the highest numeric issue."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Completed Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=4,
        status="completed",
        user_id=user.id,
        total_issues=11,
        reading_progress="completed",
        next_unread_issue_id=None,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    for position, issue_number in enumerate(
        [*(str(i) for i in range(1, 11)), "Annual 1"],
        start=1,
    ):
        async_db.add(
            Issue(
                thread_id=thread.id,
                issue_number=issue_number,
                position=position,
                status="read",
                read_at=datetime.now(UTC),
            )
        )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/threads/reactivate",
        json={"thread_id": thread.id, "issues_to_add": 2},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 13
    assert data["issues_remaining"] == 2
    assert data["next_unread_issue_number"] == "11"

    result = await async_db.execute(
        select(Issue)
        .where(Issue.thread_id == thread.id)
        .order_by(Issue.position, Issue.id)
    )
    issues = result.scalars().all()

    assert [issue.issue_number for issue in issues[-2:]] == ["11", "12"]
    assert [issue.position for issue in issues[-2:]] == [12, 13]


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_success(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test successful migration creates issues and updates thread."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == thread.id
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_id"] is not None
    assert data["issues_remaining"] == 10

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 15


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_last_exceeds_total(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails when last_issue_read > total_issues."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 30, "total_issues": 25},
    )

    assert response.status_code == 400
    assert "cannot exceed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_negative_values_blocked(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test schema validation blocks negative values."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": -1, "total_issues": 25},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """Test migration returns 404 for non-existent thread."""
    response = await auth_client.post(
        "/api/v1/threads/999:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_already_migrated(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails when thread already uses issue tracking."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=25,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 400
    assert "already uses" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migration fails for other user's threads."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_completed(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migrating a fully read thread marks it as completed."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 25, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "completed"
    assert data["next_unread_issue_id"] is None
    assert data["status"] == "completed"
    assert data["issues_remaining"] == 0

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25
    assert all(i.status == "read" for i in issues)


@pytest.mark.asyncio
async def test_migrate_thread_to_issues_unread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test migrating an unread thread."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=25,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 0, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"
    assert data["next_unread_issue_id"] is not None
    assert data["issues_remaining"] == 25

    await async_db.refresh(thread)

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25

    read_issues = [i for i in issues if i.status == "read"]
    assert len(read_issues) == 0


@pytest.mark.asyncio
async def test_create_thread_without_total_issues_maintains_backward_compat(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread without total_issues uses old system (backward compat)."""
    response = await auth_client.post(
        "/api/v1/threads/",
        json={
            "title": "Old Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Old Style Thread"
    assert data["issues_remaining"] == 10
    assert data["total_issues"] is None
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.issues_remaining == 10
    assert thread.total_issues is None
    assert not thread.uses_issue_tracking()


@pytest.mark.asyncio
async def test_create_thread_with_total_issues_enables_tracking(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Creating thread with total_issues enables issue tracking."""
    response = await auth_client.post(
        "/api/v1/threads/",
        json={
            "title": "New Style Thread",
            "format": "Comic",
            "issues_remaining": 10,
            "total_issues": 25,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Style Thread"
    assert data["total_issues"] == 25
    assert data["reading_progress"] is None

    thread = await async_db.get(Thread, data["id"])
    assert thread is not None
    assert thread.total_issues == 25
    assert thread.uses_issue_tracking()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 0


@pytest.mark.asyncio
async def test_thread_create_schema_accepts_total_issues() -> None:
    """ThreadCreate schema accepts optional total_issues field."""
    from app.schemas import ThreadCreate

    schema = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
        total_issues=25,
    )
    assert schema.total_issues == 25

    schema_without = ThreadCreate(
        title="Test Thread",
        format="Comic",
        issues_remaining=10,
    )
    assert schema_without.total_issues is None


@pytest.mark.asyncio
async def test_migration_enables_issue_tracking(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Migrating a thread enables issue tracking."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Old Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    assert thread.total_issues is None
    assert not thread.uses_issue_tracking()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}:migrateToIssues",
        json={"last_issue_read": 15, "total_issues": 25},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_issues"] == 25
    assert data["reading_progress"] == "in_progress"

    await async_db.refresh(thread)
    assert thread.total_issues == 25
    assert thread.uses_issue_tracking()

    result = await async_db.execute(select(Issue).where(Issue.thread_id == thread.id))
    issues = result.scalars().all()
    assert len(issues) == 25


@pytest.mark.asyncio
async def test_stale_endpoint_excludes_blocked_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Blocked stale threads should not appear in the stale endpoint."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)

    blocked_thread = Thread(
        title="Blocked Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        is_blocked=True,
        created_at=now,
    )
    async_db.add(blocked_thread)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/stale?days=30")
    assert response.status_code == 200
    data = response.json()
    thread_ids = {t["id"] for t in data}
    assert blocked_thread.id not in thread_ids


@pytest.mark.asyncio
async def test_stale_endpoint_includes_unblocked_stale_threads(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unblocked stale threads should appear in the stale endpoint."""
    user = await get_or_create_user_async(async_db)
    now = datetime.now(UTC)
    stale_date = now - timedelta(days=60)

    unblocked_thread = Thread(
        title="Unblocked Stale Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
        last_activity_at=stale_date,
        is_blocked=False,
        created_at=now,
    )
    async_db.add(unblocked_thread)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/stale?days=30")
    assert response.status_code == 200
    data = response.json()
    thread_ids = {t["id"] for t in data}
    assert unblocked_thread.id in thread_ids


@pytest.mark.asyncio
async def test_list_threads_issues_remaining_correct(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """issues_remaining reflects live unread count for migrated threads."""
    from app.cache import invalidate_cache

    user = await get_or_create_user_async(async_db)

    threads_data: list[tuple[str, int, int, int]] = [
        ("Series A", 10, 3, 1),
        ("Series B", 5, 1, 2),
        ("Series C", 20, 0, 3),
    ]
    expected_remaining: dict[int, int] = {}

    for title, total, unread, pos in threads_data:
        thread = Thread(
            title=title,
            format="Comic",
            issues_remaining=0,
            queue_position=pos,
            status="active",
            user_id=user.id,
            total_issues=total,
            reading_progress="in_progress",
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
        await async_db.flush()
        expected_remaining[thread.id] = unread

        for issue_num in range(1, total + 1):
            status = "unread" if issue_num > (total - unread) else "read"
            async_db.add(
                Issue(
                    thread_id=thread.id,
                    issue_number=str(issue_num),
                    position=issue_num,
                    status=status,
                    read_at=datetime.now(UTC) if status == "read" else None,
                )
            )
    await async_db.commit()

    await invalidate_cache("cache:*")
    response = await auth_client.get("/api/v1/threads/?page_size=10")
    assert response.status_code == 200
    data = response.json()

    thread_map = {t["id"]: t for t in data["threads"]}
    for tid, expected in expected_remaining.items():
        assert thread_map[tid]["issues_remaining"] == expected, (
            f"Thread {tid} expected {expected} unread, got {thread_map[tid]['issues_remaining']}"
        )


@pytest.mark.asyncio
async def test_list_threads_mixed_migrated_unmigrated(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unmigrated threads report legacy column; migrated threads report true count."""
    from app.cache import invalidate_cache

    user = await get_or_create_user_async(async_db)

    unmigrated = Thread(
        title="Old Thread",
        format="Comic",
        issues_remaining=42,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(unmigrated)
    await async_db.flush()

    migrated = Thread(
        title="New Thread",
        format="Comic",
        issues_remaining=99,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=10,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(migrated)
    await async_db.flush()

    for i in range(1, 11):
        async_db.add(
            Issue(
                thread_id=migrated.id,
                issue_number=str(i),
                position=i,
                status="unread" if i <= 3 else "read",
                read_at=datetime.now(UTC) if i > 3 else None,
            )
        )
    await async_db.commit()

    await invalidate_cache("cache:*")
    response = await auth_client.get("/api/v1/threads/?page_size=10")
    assert response.status_code == 200
    data = response.json()

    thread_map = {t["id"]: t for t in data["threads"]}

    assert thread_map[unmigrated.id]["issues_remaining"] == 42
    assert thread_map[migrated.id]["issues_remaining"] == 3


@pytest.mark.asyncio
async def test_bulk_issues_remaining_no_n_plus_one(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """List endpoint uses a single GROUP BY query instead of N per-thread COUNTs."""
    from app.cache import invalidate_cache
    from sqlalchemy import event

    user = await get_or_create_user_async(async_db)

    thread_count = 20
    for i in range(thread_count):
        t = Thread(
            title=f"Bulk Thread {i}",
            format="Comic",
            issues_remaining=0,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            total_issues=5,
            reading_progress="in_progress",
            created_at=datetime.now(UTC),
        )
        async_db.add(t)
        await async_db.flush()

        for j in range(1, 6):
            async_db.add(
                Issue(
                    thread_id=t.id,
                    issue_number=str(j),
                    position=j,
                    status="unread" if j <= 2 else "read",
                    read_at=datetime.now(UTC) if j > 2 else None,
                )
            )
    await async_db.commit()

    await invalidate_cache("cache:*")

    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        response = await auth_client.get("/api/v1/threads/?page_size=50")
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert response.status_code == 200
    data = response.json()
    assert len(data["threads"]) == thread_count

    for t_resp in data["threads"]:
        assert t_resp["issues_remaining"] == 2, (
            f"Thread {t_resp['id']} expected 2 unread, got {t_resp['issues_remaining']}"
        )

    per_thread_counts = [
        s
        for s in captured
        if "count(" in s.lower()
        and "from issues" in s.lower()
        and "group by" not in s.lower()
    ]
    assert len(per_thread_counts) == 0, (
        f"Found {len(per_thread_counts)} per-thread COUNT queries: {per_thread_counts}"
    )

    bulk_counts = [
        s
        for s in captured
        if "group by" in s.lower() and "issues" in s.lower()
    ]
    assert len(bulk_counts) == 1, (
        f"Expected 1 bulk COUNT query, found {len(bulk_counts)}: {bulk_counts}"
    )

    assert len(captured) < 15, (
        f"Expected bounded query count (<15), got {len(captured)}: {captured}"
    )


@pytest.mark.asyncio
async def test_set_current_issue_forward_correction(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test forward correction: move current issue from #6 to #8."""
    # sample_data has Batman (thread_id=2) with issues 1-5 read, 6-10 unread
    # next_unread_issue_id is issue 6 (position 6)
    thread_id = sample_data["threads"][1].id  # Batman thread
    
    # Verify initial state: issue 6 is next unread
    from sqlalchemy import select
    from app.models import Issue
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    issues = list(result.scalars().all())
    assert issues[5].issue_number == "6"  # position 6 (0-indexed = 5)
    assert issues[5].status == "unread"
    assert issues[7].issue_number == "8"  # position 8 (0-indexed = 7)
    assert issues[7].status == "unread"
    
    # Correct current issue to #8
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "8"}
    )
    assert response.status_code == 200
    data = response.json()
    
    # Verify response
    assert data["thread_id"] == thread_id
    assert data["issue_number"] == "8"
    assert data["next_issue_number"] == "8"
    assert data["issues_remaining"] == 3  # issues 8, 9, 10 unread
    
    # Verify database state: issues 1-7 should be read, 8-10 unread
    await async_db.refresh(sample_data["threads"][1])
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    issues = list(result.scalars().all())
    
    # Issues 1-7 (positions 1-7) should be read
    for i in range(7):
        assert issues[i].status == "read", f"Issue {issues[i].issue_number} should be read"
        assert issues[i].read_at is not None
    
    # Issues 8-10 (positions 8-10) should be unread
    for i in range(7, 10):
        assert issues[i].status == "unread", f"Issue {issues[i].issue_number} should be unread"
        assert issues[i].read_at is None
    
    # next_unread_issue_id should point to issue 8
    assert sample_data["threads"][1].next_unread_issue_id == issues[7].id


@pytest.mark.asyncio
async def test_set_current_issue_backward_correction(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test backward correction: move current issue from #8 to #3.

    Implementation preserves read status of issues after the target.
    After moving to #8: issues 1-7 read, 8-10 unread.
    Moving back to #3: issues 1-2 read, 3 unread, 4-7 read (preserved), 8-10 unread.
    Unread issues = {3, 8, 9, 10} = 4.
    """
    thread_id = sample_data["threads"][1].id  # Batman thread
    
    # First move to #8
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "8"}
    )
    assert response.status_code == 200
    
    # Now move backward to #3
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "3"}
    )
    assert response.status_code == 200
    data = response.json()
    
    # Verify response
    assert data["thread_id"] == thread_id
    assert data["issue_number"] == "3"
    assert data["next_issue_number"] == "3"
    assert data["issues_remaining"] == 4  # issues 3, 8, 9, 10 unread
    
    # Verify database state
    from sqlalchemy import select
    from app.models import Issue
    await async_db.refresh(sample_data["threads"][1])
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).order_by(Issue.position)
    )
    issues = list(result.scalars().all())
    
    # Issues 1-2 (positions 1-2) should be read
    for i in range(2):
        assert issues[i].status == "read", f"Issue {issues[i].issue_number} should be read"
        assert issues[i].read_at is not None
    
    # Issue 3 (position 3) should be unread (the new current)
    assert issues[2].status == "unread"
    assert issues[2].read_at is None
    
    # Issues 4-7 (positions 4-7) should remain read (preserved from move to #8)
    for i in range(3, 7):
        assert issues[i].status == "read", f"Issue {issues[i].issue_number} should be read"
        assert issues[i].read_at is not None
    
    # Issues 8-10 (positions 8-10) should remain unread
    for i in range(7, 10):
        assert issues[i].status == "unread", f"Issue {issues[i].issue_number} should be unread"
        assert issues[i].read_at is None
    
    # next_unread_issue_id should point to issue 3
    assert sample_data["threads"][1].next_unread_issue_id == issues[2].id


@pytest.mark.asyncio
async def test_set_current_issue_thread_not_found(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test 404 when thread doesn't exist."""
    response = await auth_client.post(
        "/api/v1/threads/99999:setCurrentIssue",
        json={"issue_number": "1"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_set_current_issue_not_active_thread(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test 400 when thread is not active."""
    # Wonder Woman thread (id=3) is completed
    thread_id = sample_data["threads"][2].id
    
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "1"}
    )
    assert response.status_code == 400
    assert "not active" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_set_current_issue_no_issue_tracking(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test 400 when thread doesn't use issue tracking."""
    # Superman thread (id=1) doesn't have total_issues set
    thread_id = sample_data["threads"][0].id
    
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "1"}
    )
    assert response.status_code == 400
    assert "does not use issue tracking" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_set_current_issue_nonexistent_issue(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test 404 when issue number doesn't exist in thread."""
    thread_id = sample_data["threads"][1].id  # Batman thread
    
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "999"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_set_current_issue_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Test 404 when thread belongs to another user."""
    from app.models import User, Thread
    
    # Create another user with a different username
    other_user = User(
        username="otheruser",
        id=999,
        created_at=datetime.now(UTC),
    )
    async_db.add(other_user)
    await async_db.flush()
    await async_db.refresh(other_user)
    
    # Create thread for other user
    other_thread = Thread(
        title="Other's Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        total_issues=5,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(other_thread)
    await async_db.flush()
    await async_db.refresh(other_thread)
    
    # Try to access from current user
    response = await auth_client.post(
        f"/api/v1/threads/{other_thread.id}:setCurrentIssue",
        json={"issue_number": "1"}
    )
    assert response.status_code == 404  # get_owned_thread_or_404 returns 404 for other user's thread


@pytest.mark.asyncio
async def test_set_current_issue_updates_session_pending_issue(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test that session.pending_issue_id is updated."""
    from comic_pile.session import resolve_current_session
    
    thread_id = sample_data["threads"][1].id  # Batman thread
    
    # Get the authoritative current session (what get_or_create would return)
    session = await resolve_current_session(async_db, sample_data["user"].id)
    assert session is not None
    original_session_id = session.id
    
    # Correct to issue #8
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "8"}
    )
    assert response.status_code == 200
    data = response.json()
    
    # Verify session was updated
    await async_db.refresh(session)
    target_issue = data["issue_id"]
    assert session.pending_issue_id == target_issue
    assert session.pending_thread_updated_at is not None
    assert session.id == original_session_id


@pytest.mark.asyncio
async def test_set_current_issue_preserves_already_read_issues_after_target(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Test that already-read issues after the target remain read."""
    from sqlalchemy import select

    thread_id = sample_data["threads"][1].id  # Batman thread

    # First set current to #8
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "8"}
    )
    assert response.status_code == 200

    # Manually mark issue #10 as read (simulating user read ahead)
    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == thread_id).where(Issue.issue_number == "10")
    )
    issue_10 = result.scalar_one()
    issue_10.status = "read"
    issue_10.read_at = datetime.now(UTC)
    await async_db.flush()

    # Now set current to #9 (one before #10)
    response = await auth_client.post(
        f"/api/v1/threads/{thread_id}:setCurrentIssue",
        json={"issue_number": "9"}
    )
    assert response.status_code == 200
    data = response.json()

    # Verify #10 is still read
    await async_db.refresh(issue_10)
    assert issue_10.status == "read"
    assert issue_10.read_at is not None

    # Verify issues_remaining is 1 (only #9 unread)
    assert data["issues_remaining"] == 1
    assert data["issue_number"] == "9"
    assert data["next_issue_number"] == "9"


@pytest.mark.asyncio
async def test_create_thread_normalizes_format_variants(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Thread creation normalizes Comic/Comics/digital to canonical forms."""
    user = await get_or_create_user_async(async_db)

    cases = [
        ("Comic", "Comic"),
        ("Comics", "Comic"),
        ("comic", "Comic"),
        ("comics", "Comic"),
        ("digital", "Digital"),
        ("Digital", "Digital"),
        ("Trade Paperback", "Trade Paperback"),
    ]

    for raw, expected in cases:
        response = await auth_client.post(
            "/api/v1/threads/",
            json={"title": f"Thread {raw}", "format": raw, "issues_remaining": 1},
        )
        assert response.status_code == 201, f"Failed for {raw}: {response.text}"
        data = response.json()
        assert data["format"] == expected, f"Expected {expected} for {raw}, got {data['format']}"

        result = await async_db.execute(
            select(Thread).where(Thread.id == data["id"])
        )
        db_thread = result.scalar_one()
        assert db_thread.format == expected, f"DB format mismatch for {raw}"


@pytest.mark.asyncio
async def test_update_thread_normalizes_format_variants(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Thread update normalizes Comic/Comics/digital to canonical forms."""
    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Format Test",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    cases = [
        ("Comics", "Comic"),
        ("comics", "Comic"),
        ("digital", "Digital"),
        ("Manga", "Manga"),
    ]

    for raw, expected in cases:
        response = await auth_client.put(
            f"/api/v1/threads/{thread.id}",
            json={"format": raw},
        )
        assert response.status_code == 200, f"Failed for {raw}: {response.text}"
        data = response.json()
        assert data["format"] == expected, f"Expected {expected} for {raw}, got {data['format']}"

        await async_db.refresh(thread)
        assert thread.format == expected, f"DB format mismatch for {raw}"


@pytest.mark.asyncio
async def test_queue_items_show_normalized_format(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Queue list items render normalized format values."""
    user = await get_or_create_user_async(async_db)

    for fmt in ("Comics", "digital", "Manga"):
        thread = Thread(
            title=f"Test {fmt}",
            format=fmt,
            issues_remaining=1,
            queue_position=1,
            status="active",
            user_id=user.id,
            created_at=datetime.now(UTC),
        )
        async_db.add(thread)
    await async_db.commit()

    response = await auth_client.get("/api/v1/threads/")
    assert response.status_code == 200
    data = response.json()

    formats = {item["format"] for item in data["threads"]}
    assert "Comic" in formats
    assert "Digital" in formats
    assert "Manga" in formats
    assert "Comics" not in formats
    assert "digital" not in formats

