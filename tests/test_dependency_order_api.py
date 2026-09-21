"""Dependency order-check API tests."""

from sqlalchemy import select

from app.models import Dependency, Issue, Thread, User

async def test_dependency_order_check_no_conflicts(auth_client, async_db, test_username):
    """Order check should return empty conflicts when position and dependency order agree."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    thread = Thread(
        title="Well-Ordered Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
    )
    async_db.add(thread)
    await async_db.flush()

    issue_1 = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    issue_2 = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    issue_3 = Issue(
        thread_id=thread.id,
        issue_number="3",
        position=3,
        status="unread",
    )
    async_db.add_all([issue_1, issue_2, issue_3])
    await async_db.commit()
    await async_db.refresh(thread)

    resp = await auth_client.get(f"/api/v1/threads/{thread.id}/dependency-order-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == thread.id
    assert data["conflicts"] == []

async def test_dependency_order_check_with_conflicts(auth_client, async_db, test_username):
    """Order check should detect conflicts where dependency order disagrees with position."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    thread = Thread(
        title="Conflicted Thread",
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=3,
    )
    async_db.add(thread)
    await async_db.flush()

    issue_79 = Issue(
        thread_id=thread.id,
        issue_number="79",
        position=79,
        status="unread",
    )
    issue_131 = Issue(
        thread_id=thread.id,
        issue_number="131",
        position=131,
        status="unread",
    )
    async_db.add_all([issue_79, issue_131])
    await async_db.commit()
    await async_db.refresh(issue_79)
    await async_db.refresh(issue_131)


    dep = Dependency(
        source_issue_id=issue_131.id,
        target_issue_id=issue_79.id,
    )
    async_db.add(dep)
    await async_db.commit()

    resp = await auth_client.get(f"/api/v1/threads/{thread.id}/dependency-order-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == thread.id
    assert len(data["conflicts"]) == 1

    conflict = data["conflicts"][0]
    assert conflict["issue_id"] == issue_131.id
    assert conflict["issue_number"] == "131"
    assert conflict["position"] == 131
    assert len(conflict["dependency_requires_before"]) == 1
    assert conflict["dependency_requires_before"][0]["issue_id"] == issue_79.id
    assert conflict["dependency_requires_before"][0]["issue_number"] == "79"
    assert conflict["dependency_requires_before"][0]["position"] == 79
    assert "position 131 comes after issue at position 79" in conflict["conflict"]

async def test_dependency_order_check_unauthorized_thread(auth_client, async_db, test_username):
    """Order check should return 404 for other users' threads."""
    other_user = User(username="other", email="other@example.com", password_hash="hash")
    async_db.add(other_user)
    await async_db.commit()

    other_thread = Thread(
        title="Other User Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=other_user.id,
    )
    async_db.add(other_thread)
    await async_db.commit()
    await async_db.refresh(other_thread)

    resp = await auth_client.get(f"/api/v1/threads/{other_thread.id}/dependency-order-check")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

async def test_dependency_order_check_nonexistent_thread(auth_client):
    """Order check should return 404 for non-existent thread."""
    resp = await auth_client.get("/api/v1/threads/99999/dependency-order-check")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()

async def test_dependency_order_check_cross_thread_dependencies(
    auth_client, async_db, test_username
):
    """Order check should only check in-thread dependencies, not cross-thread."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    thread2 = Thread(
        title="Thread 2",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    async_db.add_all([thread1, thread2])
    await async_db.flush()

    thread1_issue = Issue(
        thread_id=thread1.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    thread2_issue = Issue(
        thread_id=thread2.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([thread1_issue, thread2_issue])
    await async_db.commit()
    await async_db.refresh(thread1_issue)
    await async_db.refresh(thread2_issue)


    dep = Dependency(
        source_issue_id=thread1_issue.id,
        target_issue_id=thread2_issue.id,
    )
    async_db.add(dep)
    await async_db.commit()

    resp = await auth_client.get(f"/api/v1/threads/{thread1.id}/dependency-order-check")
    assert resp.status_code == 200
    data = resp.json()
    assert data["thread_id"] == thread1.id
    assert data["conflicts"] == []

