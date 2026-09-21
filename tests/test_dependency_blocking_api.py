"""Dependency blocking semantics API tests."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Issue, Thread, User

async def test_issue_dependency_does_not_block_until_target_is_next_unread(
    auth_client, async_db, test_username
):
    """Future issue dependency should block only when target becomes next unread."""
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
    assert target_thread.id not in blocked_resp.json(), (
        "Thread should remain roll-eligible until the dependency target is next unread"
    )

    info_before_target = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_before_target.status_code == 200
    assert info_before_target.json()["is_blocked"] is False

    target_issue_1.status = "read"
    target_issue_1.read_at = datetime.now(UTC)
    target_issue_2.status = "read"
    target_issue_2.read_at = datetime.now(UTC)
    target_thread.next_unread_issue_id = target_issue_3.id
    await async_db.commit()
    await async_db.refresh(target_thread)

    blocked_after = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_after.status_code == 200
    assert target_thread.id in blocked_after.json(), (
        "Thread should remain blocked when next unread issue has unread prerequisite"
    )

    info_resp = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_resp.status_code == 200
    assert info_resp.json()["is_blocked"] is True

async def test_issue_dependency_waits_for_first_matching_target_in_same_thread(
    auth_client, async_db, test_username
):
    """Multiple future dependencies should block only when one target is next unread."""
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
    assert target_thread.id not in blocked_resp.json(), (
        "Thread should remain roll-eligible before the first dependency target"
    )

    # Now read issue 1, making the first dependency target the next unread issue.
    target_issue_1.status = "read"
    target_issue_1.read_at = datetime.now(UTC)
    target_thread.next_unread_issue_id = target_issue_3.id
    await async_db.commit()
    await async_db.refresh(target_thread)

    # Still blocked after advancing next_unread
    blocked_after = await auth_client.get("/api/v1/dependencies/blocked")
    assert blocked_after.status_code == 200
    assert target_thread.id in blocked_after.json(), (
        "Thread should remain blocked when next unread issue has unread prerequisite"
    )

    info_resp = await auth_client.post(f"/api/v1/threads/{target_thread.id}:getBlockingInfo")
    assert info_resp.status_code == 200

async def test_dependency_rejects_already_read_target(auth_client, async_db, test_username):
    """POST /api/v1/dependencies/ returns 400 when target issue is behind next-unread."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Prereq Series",
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
        issue_number="1",
        position=1,
        status="unread",
    )
    target_issue_1 = Issue(
        thread_id=target_thread.id,
        issue_number="8",
        position=1,
        status="read",
        read_at=datetime.now(UTC),
    )
    target_issue_2 = Issue(
        thread_id=target_thread.id,
        issue_number="9",
        position=2,
        status="unread",
    )
    async_db.add_all([source_issue, target_issue_1, target_issue_2])
    await async_db.flush()

    target_thread.next_unread_issue_id = target_issue_2.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue_1)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue_1.id,
        },
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "already been read" in detail
    assert "#8" in detail
    assert "#9" in detail

async def test_dependency_exact_next_unread_no_warning(auth_client, async_db, test_username):
    """POST /api/v1/dependencies/ returns 201 with no warning for exact next-unread target."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    source_thread = Thread(
        title="Exact Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    target_thread = Thread(
        title="Exact Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
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

    target_thread.next_unread_issue_id = target_issue.id
    await async_db.commit()
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue.id,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data.get("warning") is None

async def test_dependency_future_target_returns_warning(auth_client, async_db, test_username):
    """POST /api/v1/dependencies/ returns 201 with warning when target is ahead of next-unread."""
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
    await async_db.refresh(source_issue)
    await async_db.refresh(target_issue_3)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={
            "source_type": "issue",
            "source_id": source_issue.id,
            "target_type": "issue",
            "target_id": target_issue_3.id,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["warning"] is not None
    assert "#10" in data["warning"]
    assert "#8" in data["warning"]
    assert "2 issues" in data["warning"]
    assert "will block when the target thread reaches it" in data["warning"]

