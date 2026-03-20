"""Dependency API tests."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Issue, Thread, User


@pytest.mark.asyncio
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
    )
    t2 = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([t1, t2])
    await async_db.commit()
    await async_db.refresh(t1)
    await async_db.refresh(t2)

    create_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": t1.id,
            "target_type": "thread",
            "target_id": t2.id,
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


@pytest.mark.asyncio
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
    )
    async_db.add(t1)
    await async_db.commit()
    await async_db.refresh(t1)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": t1.id,
            "target_type": "thread",
            "target_id": t1.id,
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_thread_dependency_returns_400(auth_client, async_db, test_username):
    """Creating duplicate thread dependency should return 400, not 500 (issue #255)."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Source",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="Target",
        format="Comic",
        issues_remaining=2,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([t1, t2])
    await async_db.commit()
    await async_db.refresh(t1)
    await async_db.refresh(t2)

    create_resp1 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": t1.id,
            "target_type": "thread",
            "target_id": t2.id,
        },
    )
    assert create_resp1.status_code == 201

    create_resp2 = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": t1.id,
            "target_type": "thread",
            "target_id": t2.id,
        },
    )
    assert create_resp2.status_code == 400
    assert "already exists" in create_resp2.json()["detail"].lower()


@pytest.mark.asyncio
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
    assert info_resp.json()["is_blocked"] is True
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_issue_dependency_blocks_when_target_not_next_unread(
    auth_client, async_db, test_username
):
    """Issue dependency should block thread even when target is not next_unread_issue (issue #270)."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Stormwatch Vol. 2",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    target_thread = Thread(
        title="Planetary",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=3,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue = Issue(
        thread_id=source_thread.id,
        issue_number="11",
        position=1,
        status="unread",
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id,
        issue_number="8",
        position=1,
        status="unread",
    )
    target_issue_2 = Issue(
        thread_id=target_thread.id,
        issue_number="9",
        position=2,
        status="unread",
    )
    target_issue_3 = Issue(
        thread_id=target_thread.id,
        issue_number="10",
        position=3,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue_1, target_issue_2, target_issue_3])
    await async_db.flush()

    target_thread.next_unread_issue_id = target_issue_1.id
    await async_db.commit()
    await async_db.refresh(target_thread)

    create_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue_3.id,
        },
    )
    assert create_resp.status_code == 201

    blocked_resp = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_resp.status_code == 200
    # New behavior: should NOT be blocked since dependency is on issue 3, not next unread issue 1
    assert target_thread.id not in blocked_resp.json(), (
        "Thread should NOT be blocked when dependency is on future issue, not next unread"
    )

    # Read issues 1 and 2 so that issue 3 (which has the dep) becomes next unread
    target_issue_1.status = "read"
    target_issue_1.read_at = datetime.now(UTC)
    target_issue_2.status = "read"
    target_issue_2.read_at = datetime.now(UTC)
    target_thread.next_unread_issue_id = target_issue_3.id
    await async_db.commit()
    await async_db.refresh(target_thread)

    # Now it SHOULD be blocked since next unread issue 3 has unread prerequisite
    blocked_after = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_after.status_code == 200
    assert target_thread.id in blocked_after.json(), (
        "Thread should be blocked when next unread issue has unread prerequisite"
    )

    info_resp = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_resp.status_code == 200
    assert info_resp.json()["is_blocked"] is True


@pytest.mark.asyncio
async def test_issue_dependency_blocking_multiple_issues_same_thread(
    auth_client, async_db, test_username
):
    """Multiple dependencies on different issues in same thread should all block."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Prequel Series",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
    )
    target_thread = Thread(
        title="Main Series",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=5,
    )
    async_db.add_all([source_thread, target_thread])
    await async_db.flush()

    source_issue_1 = Issue(
        thread_id=source_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    source_issue_2 = Issue(
        thread_id=source_thread.id,
        issue_number="2",
        position=2,
        status="unread",
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue_3 = Issue(
        thread_id=target_thread.id,
        issue_number="3",
        position=3,
        status="unread",
    )
    target_issue_5 = Issue(
        thread_id=target_thread.id,
        issue_number="5",
        position=5,
        status="unread",
    )
    async_db.add_all(
        [source_issue_1, source_issue_2, target_issue_1, target_issue_3, target_issue_5]
    )
    await async_db.flush()

    target_thread.next_unread_issue_id = target_issue_1.id
    await async_db.commit()

    dep1_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue_1.id,
            "target_type": "issue",
            "target_id": target_issue_3.id,
        },
    )
    assert dep1_resp.status_code == 201

    dep2_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue_2.id,
            "target_type": "issue",
            "target_id": target_issue_5.id,
        },
    )
    assert dep2_resp.status_code == 201

    blocked_resp = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_resp.status_code == 200
    # New behavior: should NOT be blocked since dependencies are on issues 3 and 5, not next unread issue 1
    assert target_thread.id not in blocked_resp.json(), (
        "Thread should NOT be blocked when dependencies are on future issues, not next unread"
    )

    # Now read issue 1, making next unread issue 2
    target_issue_1.status = "read"
    target_issue_1.read_at = datetime.now(UTC)
    target_thread.next_unread_issue_id = target_issue_3.id
    await async_db.commit()
    await async_db.refresh(target_thread)

    # Now it SHOULD be blocked since next unread issue 3 has unread prerequisite
    blocked_after = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_after.status_code == 200
    assert target_thread.id in blocked_after.json(), (
        "Thread should be blocked when next unread issue has unread prerequisite"
    )

    info_resp = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_resp.status_code == 200
@pytest.mark.asyncio
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
    )
    t2 = Thread(
        title="Dependent Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
    )
    async_db.add_all([t1, t2])
    await async_db.commit()
    await async_db.refresh(t1)
    await async_db.refresh(t2)

    create_dep_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "thread",
            "source_id": t1.id,
            "target_type": "thread",
            "target_id": t2.id,
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
