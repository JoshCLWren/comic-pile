"""Dependency notes API tests."""

import pytest
from sqlalchemy import select

from app.models import Issue, Thread, User

async def test_update_dependency_note_success(auth_client, async_db, test_username):
    """PATCH should update note on dependency and return updated dependency."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Note Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="Note Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
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
    assert create_resp.json()["note"] is None

    update_resp = await auth_client.patch(
        f"/api/v1/dependencies/{dep_id}",
        json={"note": "This is a crossover - read first"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["note"] == "This is a crossover - read first"

    get_resp = await auth_client.get(f"/api/v1/dependencies/{dep_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["note"] == "This is a crossover - read first"

async def test_update_dependency_note_too_long_returns_422(auth_client, async_db, test_username):
    """PATCH with note > 255 chars should return 422."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Note Source 2",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="Note Target 2",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
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

    long_note = "x" * 256
    update_resp = await auth_client.patch(
        f"/api/v1/dependencies/{dep_id}",
        json={"note": long_note},
    )
    assert update_resp.status_code == 422

async def test_update_dependency_note_clears_note(auth_client, async_db, test_username):
    """PATCH with note: null should clear the note."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="Note Source 3",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="Note Target 3",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
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

    await auth_client.patch(
        f"/api/v1/dependencies/{dep_id}",
        json={"note": "Some note"},
    )

    clear_resp = await auth_client.patch(
        f"/api/v1/dependencies/{dep_id}",
        json={"note": None},
    )
    assert clear_resp.status_code == 200
    assert clear_resp.json()["note"] is None

async def test_dependency_note_in_list_endpoint(auth_client, async_db, test_username):
    """List endpoint should include note in response."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(
        title="List Note Source",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    t2 = Thread(
        title="List Note Target",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
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

    await auth_client.patch(
        f"/api/v1/dependencies/{dep_id}",
        json={"note": "Note visible in list"},
    )

    list_resp = await auth_client.get(f"/api/v1/threads/{t2.id}/dependencies")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert len(data["blocked_by"]) == 1
    assert data["blocked_by"][0]["note"] == "Note visible in list"

