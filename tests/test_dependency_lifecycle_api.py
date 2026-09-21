"""Dependency lifecycle API tests."""

from sqlalchemy import select

from app.models import Dependency, Issue, Thread, User

async def test_dependency_api_lifecycle(auth_client, async_db, test_username):
    """Create/read/delete dependency endpoints should work for owned threads."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    t2 = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
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

    create_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp.status_code == 201
    dep_id = create_resp.json()["id"]

    blocked_resp = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_resp.status_code == 200
    assert t2.id in blocked_resp.json()

    info_resp = await auth_client.post(f"/api/v1/threads/{t2.id}:getBlockingInfo")
    assert info_resp.status_code == 200
    assert info_resp.json()["is_blocked"] is True

    get_resp = await auth_client.get(f"/api/v1/dependencies/{dep_id}")
    assert get_resp.status_code == 200

    delete_resp = await auth_client.delete(f"/api/v1/dependencies/{dep_id}")
    assert delete_resp.status_code == 200

async def test_dependency_rejects_self(auth_client, async_db, test_username):
    """Creating self-dependency should return 400."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Solo",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    async_db.add(t1)
    await async_db.flush()

    issue = Issue(thread_id=t1.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    t1.next_unread_issue_id = issue.id
    await async_db.commit()
    await async_db.refresh(issue)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": issue.id,
            "target_type": "issue",
            "target_id": issue.id,
        },
    )
    assert resp.status_code == 400

async def test_duplicate_thread_dependency_returns_400(auth_client, async_db, test_username):
    """Creating duplicate issue dependency should return 400, not 500 (issue #255)."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    t2 = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
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

    create_resp1 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp1.status_code == 201

    create_resp2 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp2.status_code == 400
    assert "already exists" in create_resp2.json()["detail"].lower()

    # Verify exactly one dependency exists in the database
    result = await async_db.execute(
        select(Dependency).where(
            Dependency.source_issue_id == source_issue.id,
            Dependency.target_issue_id == target_issue.id,
        )
    )
    deps = result.scalars().all()
    assert len(deps) == 1

async def test_issue_dependency_api_lifecycle(auth_client, async_db, test_username):
    """Create/read/delete issue dependency endpoints should work for owned issues."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Source Issue Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    target_thread = Thread(
        title="Target Issue Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue.id
    target_thread.next_unread_issue_id = target_issue.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)
    await async_db.refresh(target_thread)

    create_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp.status_code == 201

    blocked_resp = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_resp.status_code == 200
    assert target_thread.id in blocked_resp.json()

    info_resp = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_resp.status_code == 200
    info = info_resp.json()
    assert info["is_blocked"] is True
    assert info["blocking_reasons"]
    assert "#1" in info["blocking_reasons"][0].lower()
    assert info["blocking_dependencies"]
    assert info["blocking_dependencies"][0]["thread_id"] == source_thread.id
    assert info["blocking_dependencies"][0]["thread_title"] == source_thread.title
    assert "source issue thread" in info["blocking_dependencies"][0]["label"].lower()
    target_thread = Thread(
        title="Negative Target Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)
    await async_db.refresh(source_thread)

    self_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": source_issue.id,
        },
    )
    assert self_resp.status_code == 400
    assert "self" in self_resp.json()["detail"].lower()

    mixed_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": source_thread.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert mixed_resp.status_code == 400
    assert "mixed" in mixed_resp.json()["detail"].lower()

async def test_duplicate_dependency_returns_400(auth_client, async_db, test_username):
    """Creating duplicate dependency should return 400, not 500 (issue #255)."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Dup Source Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    target_thread = Thread(
        title="Dup Target Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue])
    await async_db.flush()

    source_thread.next_unread_issue_id = source_issue.id
    target_thread.next_unread_issue_id = target_issue.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)

    create_resp1 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp1.status_code == 201

    create_resp2 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_resp2.status_code == 400
    assert "already exists" in create_resp2.json()["detail"].lower()

async def test_delete_dependency_clears_blocked_flag(auth_client, async_db, test_username):
    """Regression test for issue #269: Deleting a dependency should clear the blocked flag."""
    from sqlalchemy import select
    from app.models import Thread, User

    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Prerequisite Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    t2 = Thread(
        title="Dependent Thread",
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

    create_dep_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert create_dep_resp.status_code == 201
    dep_id = create_dep_resp.json()["id"]

    await async_db.commit()
    await async_db.refresh(t2)

    assert t2.is_blocked is True, "Target thread should be blocked after creating dependency"

    delete_resp = await auth_client.delete(
        f"/api/v1/dependencies/{dep_id}",
    )
    assert delete_resp.status_code == 200

    await async_db.commit()
    await async_db.refresh(t2)

    assert t2.is_blocked is False, "Target thread should not be blocked after deleting dependency"

async def test_delete_nonexistent_dependency_returns_404(auth_client):
    """Deleting a non-existent dependency should return 404."""
    fake_dep_id = 99999
    delete_resp = await auth_client.delete(f"/api/v1/dependencies/{fake_dep_id}")
    assert delete_resp.status_code == 404
    assert "not found" in delete_resp.json()["detail"].lower()

