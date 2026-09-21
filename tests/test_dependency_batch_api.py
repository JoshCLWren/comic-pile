"""Dependency batch blocking-info API tests."""

import pytest
from sqlalchemy import select

from app.models import Dependency, Issue, Thread, User

async def test_batch_blocking_info_multiple_threads(auth_client, async_db, test_username):
    """Batch endpoint returns blocking info for all requested threads."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Batch Source A",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    t2 = Thread(
        title="Batch Target B",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    t3 = Thread(
        title="Batch Loner C",
        format="Comic",
        issues_remaining=1,
        queue_position=3,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add_all([t1, t2, t3])
    await async_db.flush()

    source_issue = Issue(thread_id=t1.id, issue_number="1", position=1, status="unread")
    target_issue = Issue(thread_id=t2.id, issue_number="1", position=1, status="unread")
    loner_issue = Issue(thread_id=t3.id, issue_number="1", position=1, status="unread")
    async_db.add_all([source_issue, target_issue, loner_issue])
    await async_db.flush()

    t1.next_unread_issue_id = source_issue.id
    t2.next_unread_issue_id = target_issue.id
    t3.next_unread_issue_id = loner_issue.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)
    await async_db.refresh(loner_issue)

    dep_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert dep_resp.status_code == 201

    resp = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [t1.id, t2.id, t3.id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    threads = data["threads"]

    assert str(t1.id) in threads
    assert str(t2.id) in threads
    assert str(t3.id) in threads

    assert threads[str(t1.id)]["is_blocked"] is False
    assert threads[str(t1.id)]["blocking_reasons"] == []

    assert threads[str(t2.id)]["is_blocked"] is True
    assert len(threads[str(t2.id)]["blocking_reasons"]) > 0
    assert len(threads[str(t2.id)]["blocking_dependencies"]) > 0
    assert threads[str(t2.id)]["blocking_dependencies"][0]["thread_id"] == t1.id

    assert threads[str(t3.id)]["is_blocked"] is False
    assert threads[str(t3.id)]["blocking_reasons"] == []
    assert threads[str(t3.id)]["blocking_dependencies"] == []

async def test_batch_blocking_info_single_thread(auth_client, async_db, test_username):
    """Batch endpoint with one thread ID returns same result as per-thread endpoint."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Single Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    t2 = Thread(
        title="Single Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add_all([t1, t2])
    await async_db.flush()

    source_issue = Issue(thread_id=t1.id, issue_number="1", position=1, status="unread")
    target_issue = Issue(thread_id=t2.id, issue_number="1", position=1, status="unread")
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()

    t1.next_unread_issue_id = source_issue.id
    t2.next_unread_issue_id = target_issue.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)

    dep_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert dep_resp.status_code == 201

    single_resp = await auth_client.post(f"/api/v1/threads/{t2.id}:getBlockingInfo")
    assert single_resp.status_code == 200
    single_data = single_resp.json()

    batch_resp = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [t2.id]},
    )
    assert batch_resp.status_code == 200
    batch_data = batch_resp.json()

    assert batch_data["threads"][str(t2.id)]["is_blocked"] == single_data["is_blocked"]
    assert batch_data["threads"][str(t2.id)]["blocking_reasons"] == single_data["blocking_reasons"]

async def test_batch_blocking_info_no_n_plus_one(
    auth_client,
    async_db,
    db_engine,
) -> None:
    """Batch endpoint uses one query, not N per-thread queries."""
    from app.cache import invalidate_cache
    from sqlalchemy import event
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread_count = 10
    thread_ids: list[int] = []
    for i in range(thread_count):
        t = Thread(
            title=f"Bulk Block {i}",
            format="Comic",
            issues_remaining=1,
            queue_position=i + 1,
            status="active",
            user_id=user.id,
            total_issues=1,
        )
        async_db.add(t)
        await async_db.flush()
        issue = Issue(thread_id=t.id, issue_number="1", position=1, status="unread")
        async_db.add(issue)
        await async_db.flush()
        t.next_unread_issue_id = issue.id
        thread_ids.append(t.id)

    # Make first thread block all the others via chain dependencies
    for i in range(1, thread_count):
        dep = Dependency(
            source_issue_id=(
                await async_db.execute(
                    select(Issue.id).where(Issue.thread_id == thread_ids[0])
                )
            ).scalar_one(),
            target_issue_id=(
                await async_db.execute(
                    select(Issue.id).where(Issue.thread_id == thread_ids[i])
                )
            ).scalar_one(),
        )
        async_db.add(dep)
    await async_db.commit()

    await invalidate_cache("cache:*")

    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        captured.append(str(statement))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        response = await auth_client.post(
            "/api/v1/threads:getBlockingInfo",
            json={"thread_ids": thread_ids},
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert response.status_code == 200
    data = response.json()
    threads = data["threads"]
    assert len(threads) == thread_count

    # First thread is not blocked, all others are
    assert threads[str(thread_ids[0])]["is_blocked"] is False
    for i in range(1, thread_count):
        assert threads[str(thread_ids[i])]["is_blocked"] is True

    # Verify that no per-thread COUNT query was issued
    per_thread_counts = [
        s
        for s in captured
        if "count(" in s.lower()
        and "threads" in s.lower()
        and "user_id" in s.lower()
    ]
    # One COUNT is expected (the ownership validation query with IN clause)
    assert len(per_thread_counts) <= 1, (
        f"Expected at most 1 COUNT query, found {len(per_thread_counts)}: {per_thread_counts}"
    )

    # Verify query count is bounded (not exploding with N threads)
    assert len(captured) < 20, (
        f"Expected bounded query count (<20), got {len(captured)}: {captured}"
    )

async def test_batch_blocking_info_cross_user_isolation(auth_client, async_db, test_username):
    """Batch endpoint returns 404 when thread_ids include another user's thread."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    other_user = User(username="other_batch", email="other_batch@example.com", password_hash="hash")
    async_db.add(other_user)
    await async_db.flush()

    t1 = Thread(
        title="My Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    t2 = Thread(
        title="Their Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        total_issues=1,
    )
    async_db.add_all([t1, t2])
    await async_db.flush()

    issue1 = Issue(thread_id=t1.id, issue_number="1", position=1, status="unread")
    issue2 = Issue(thread_id=t2.id, issue_number="1", position=1, status="unread")
    async_db.add_all([issue1, issue2])
    await async_db.flush()

    t1.next_unread_issue_id = issue1.id
    t2.next_unread_issue_id = issue2.id
    await async_db.commit()

    resp = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [t1.id, t2.id]},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

async def test_batch_blocking_info_empty_list(auth_client):
    """Empty thread_ids returns 422 validation error."""
    resp = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": []},
    )
    assert resp.status_code == 422

async def test_batch_blocking_info_nonexistent_threads(auth_client, async_db, test_username):
    """Nonexistent thread IDs return 404."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Existing Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add(t1)
    await async_db.flush()

    issue = Issue(thread_id=t1.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    t1.next_unread_issue_id = issue.id
    await async_db.commit()

    resp = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [t1.id, 99999]},
    )
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

