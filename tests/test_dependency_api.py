"""Dependency API tests."""

import pytest
from sqlalchemy import select

from app.models import Thread, User


@pytest.mark.asyncio
async def test_dependency_api_lifecycle(auth_client, async_db, test_username):
    """Create/read/delete dependency endpoints should work for owned threads."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    t1 = Thread(title="Source", format="Comic", issues_remaining=2, queue_position=1, status="active", user_id=user.id)
    t2 = Thread(title="Target", format="Comic", issues_remaining=2, queue_position=2, status="active", user_id=user.id)
    async_db.add_all([t1, t2])
    await async_db.commit()
    await async_db.refresh(t1)
    await async_db.refresh(t2)

    create_resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={"source_type": "thread", "source_id": t1.id, "target_type": "thread", "target_id": t2.id},
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

    t1 = Thread(title="Solo", format="Comic", issues_remaining=2, queue_position=1, status="active", user_id=user.id)
    async_db.add(t1)
    await async_db.commit()
    await async_db.refresh(t1)

    resp = await auth_client.post(
        "/api/v1/dependencies/",
        json={"source_type": "thread", "source_id": t1.id, "target_type": "thread", "target_id": t1.id},
    )
    assert resp.status_code == 400
