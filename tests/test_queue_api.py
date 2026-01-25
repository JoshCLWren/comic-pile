"""Tests for queue API endpoints."""

import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import select

from app.models import Thread
from comic_pile.queue import get_roll_pool, get_stale_threads, move_to_position


@pytest.mark.asyncio
async def test_move_to_position(auth_client, db, sample_data):
    """PUT /queue/threads/{id}/position/ works."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["queue_position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    assert thread1.queue_position == 2
    assert thread2.queue_position == 3
    assert thread4.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_front(auth_client, db, sample_data):
    """PUT /queue/threads/{id}/front/ moves to position 1."""
    thread_id = sample_data["threads"][4].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["queue_position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    assert thread1.queue_position == 2


@pytest.mark.asyncio
async def test_move_to_back(auth_client, db, sample_data):
    """PUT /queue/threads/{id}/back/ moves to last position."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    # After moving to back, thread is at position 5 (last of 5 threads)
    assert data["queue_position"] == 5

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_queue_order_preserved(auth_client, db, sample_data):
    """Other threads shift correctly when one moves."""
    thread_id = sample_data["threads"][1].id
    new_position = 4

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 4

    thread3 = db.get(Thread, sample_data["threads"][2].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    thread5 = db.get(Thread, sample_data["threads"][4].id)

    assert thread3.queue_position == 2
    assert thread4.queue_position == 3
    assert thread5.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_invalid(auth_client, db, sample_data):
    """Moving to invalid position caps at boundaries."""
    thread_id = sample_data["threads"][2].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 999}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_zero_fails_validation(auth_client, db, sample_data):
    """Moving to position 0 fails validation."""
    thread_id = sample_data["threads"][2].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_roll_pool(auth_client, sample_data):
    """GET /threads/ returns threads ordered by position."""
    response = await auth_client.get("/api/threads/")
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 5

    for i in range(len(data) - 1):
        assert data[i]["queue_position"] <= data[i + 1]["queue_position"]


@pytest.mark.asyncio
async def test_move_completed_thread(auth_client, db, sample_data):
    """Moving completed thread works correctly."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_nonexistent_thread(auth_client):
    """Returns 404 for non-existent thread."""
    response = await auth_client.put("/api/queue/threads/999/front/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_move_back_thread_forward(db, sample_data):
    """Moving thread from front to back shifts other threads up."""
    from comic_pile.queue import move_to_back

    thread_id = sample_data["threads"][0].id
    user_id = sample_data["user"].id

    move_to_back(thread_id, user_id, db)

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5

    thread1 = db.get(Thread, sample_data["threads"][1].id)
    thread2 = db.get(Thread, sample_data["threads"][2].id)
    thread3 = db.get(Thread, sample_data["threads"][3].id)
    thread4 = db.get(Thread, sample_data["threads"][4].id)

    assert thread1.queue_position == 1
    assert thread2.queue_position == 2
    assert thread3.queue_position == 3
    assert thread4.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_front_nonexistent(db):
    """Move to front of nonexistent thread handles gracefully (no exception raised)."""
    from comic_pile.queue import move_to_front

    # Should not raise an exception
    result = move_to_front(999, 1, db)
    assert result is None


@pytest.mark.asyncio
async def test_move_to_back_nonexistent(db):
    """Move to back of nonexistent thread handles gracefully (no exception raised)."""
    from comic_pile.queue import move_to_back

    # Should not raise an exception
    result = move_to_back(999, 1, db)
    assert result is None


@pytest.mark.asyncio
async def test_move_to_position_nonexistent(db):
    """Move to position of nonexistent thread handles gracefully (no exception raised)."""
    from comic_pile.queue import move_to_position

    # Should not raise an exception
    result = move_to_position(999, 1, 1, db)
    assert result is None


@pytest.mark.asyncio
async def test_move_to_same_position(db, sample_data):
    """Moving to same position is a no-op."""
    from comic_pile.queue import move_to_position

    thread_id = sample_data["threads"][2].id
    user_id = sample_data["user"].id

    move_to_position(thread_id, user_id, 3, db)

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 3

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)

    assert thread1.queue_position == 1
    assert thread2.queue_position == 2
    assert thread4.queue_position == 4


@pytest.mark.asyncio
async def test_setup_stale_threads(db):
    """Returns threads inactive for specified days."""
    from datetime import datetime, timedelta

    from app.models import User
    from comic_pile.queue import get_stale_threads

    now = datetime.now()

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    stale_thread = Thread(
        title="Old Thread",
        format="Comic",
        status="active",
        queue_position=1,
        last_activity_at=now - timedelta(days=10),
        user_id=user.id,
    )
    recent_thread = Thread(
        title="Recent Thread",
        format="Comic",
        status="active",
        queue_position=2,
        last_activity_at=now - timedelta(days=3),
        user_id=user.id,
    )
    null_activity_thread = Thread(
        title="No Activity Thread",
        format="Comic",
        status="active",
        queue_position=3,
        last_activity_at=None,
        user_id=user.id,
    )

    db.add_all([stale_thread, recent_thread, null_activity_thread])
    db.commit()

    stale = get_stale_threads(user.id, db, days=7)

    assert len(stale) == 2
    stale_ids = [t.id for t in stale]
    assert stale_thread.id in stale_ids
    assert null_activity_thread.id in stale_ids
    assert recent_thread.id not in stale_ids


@pytest.mark.asyncio
async def test_get_stale_threads_custom_days(db):
    """Returns stale threads based on custom days threshold."""
    from datetime import datetime, timedelta

    from app.models import User
    from comic_pile.queue import get_stale_threads

    now = datetime.now()

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    thread_5_days = Thread(
        title="5 Days Old",
        format="Comic",
        status="active",
        queue_position=1,
        last_activity_at=now - timedelta(days=5),
        user_id=user.id,
    )
    thread_15_days = Thread(
        title="15 Days Old",
        format="Comic",
        status="active",
        queue_position=2,
        last_activity_at=now - timedelta(days=15),
        user_id=user.id,
    )

    db.add_all([thread_5_days, thread_15_days])
    db.commit()

    stale = get_stale_threads(user.id, db, days=10)

    assert len(stale) == 1
    assert stale[0].id == thread_15_days.id


@pytest.mark.asyncio
async def test_get_stale_threads_excludes_inactive(db):
    """Only returns active threads regardless of activity."""
    from datetime import datetime, timedelta

    from app.models import User
    from comic_pile.queue import get_stale_threads

    now = datetime.now()

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    stale_inactive_thread = Thread(
        title="Stale Inactive",
        format="Comic",
        status="completed",
        queue_position=1,
        last_activity_at=now - timedelta(days=10),
        user_id=user.id,
    )
    stale_active_thread = Thread(
        title="Stale Active",
        format="Comic",
        status="active",
        queue_position=2,
        last_activity_at=now - timedelta(days=10),
        user_id=user.id,
    )

    db.add_all([stale_inactive_thread, stale_active_thread])
    db.commit()

    stale = get_stale_threads(user.id, db, days=7)

    assert len(stale) == 1
    assert stale[0].id == stale_active_thread.id


@pytest.mark.asyncio
async def test_get_stale_threads(db):
    """Test GET /stale-threads returns stale threads."""
    from app.models import User

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    thread1 = Thread(
        title="Thread 1",
        format="Comic",
        status="active",
        queue_position=2,
        user_id=user.id,
    )
    thread2 = Thread(
        title="Thread 2",
        format="Comic",
        status="active",
        queue_position=1,
        user_id=user.id,
    )
    thread3 = Thread(
        title="Thread 3",
        format="Comic",
        status="completed",
        queue_position=3,
        user_id=user.id,
    )
    thread4 = Thread(
        title="Thread 4",
        format="Comic",
        status="active",
        queue_position=0,
        user_id=user.id,
    )

    db.add_all([thread1, thread2, thread3, thread4])
    db.commit()

    roll_pool = get_roll_pool(user.id, db)

    assert len(roll_pool) == 2
    assert roll_pool[0].id == thread2.id
    assert roll_pool[1].id == thread1.id


@pytest.mark.asyncio
async def test_jump_to_far_position(auth_client, db, sample_data):
    """Jump from position 1 to position 5 works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 5}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5

    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread3 = db.get(Thread, sample_data["threads"][2].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    thread5 = db.get(Thread, sample_data["threads"][4].id)

    assert thread2.queue_position == 1
    assert thread3.queue_position == 2
    assert thread4.queue_position == 3
    assert thread5.queue_position == 4


@pytest.mark.asyncio
async def test_jump_to_near_position(auth_client, db, sample_data):
    """Jump from position 5 to position 2 works correctly."""
    thread_id = sample_data["threads"][4].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 2}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 2

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread3 = db.get(Thread, sample_data["threads"][2].id)

    assert thread1.queue_position == 1
    assert thread2.queue_position == 3
    assert thread3.queue_position == 4


@pytest.mark.asyncio
async def test_jump_beyond_last_position(auth_client, db, sample_data):
    """Jumping beyond last position caps at last position."""
    thread_id = sample_data["threads"][0].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 999}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_jump_to_negative_position_fails_validation(auth_client, sample_data):
    """Jumping to negative position fails validation."""
    thread_id = sample_data["threads"][4].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": -5}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_jump_to_zero_position_fails_validation(auth_client, sample_data):
    """Jumping to position 0 fails validation."""
    thread_id = sample_data["threads"][4].id

    response = await auth_client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_move_to_back_empty_queue(db):
    """move_to_back returns early when queue is empty.

    This covers the max_position is None branch (line 47).
    """
    from comic_pile.queue import move_to_back
    from app.models import User, Thread
    from sqlalchemy import delete

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    db.execute(delete(Thread))
    db.commit()

    move_to_back(999, user.id, db)


@pytest.mark.asyncio
async def test_move_to_position_no_other_threads(db):
    """move_to_position when no other threads exist."""
    from comic_pile.queue import move_to_position
    from app.models import User, Thread
    from sqlalchemy import delete

    user = db.execute(select(User).where(User.username == "test_user")).scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(), id=1)
        db.add(user)
        db.commit()
        db.refresh(user)

    db.execute(delete(Thread))
    db.commit()

    thread = Thread(
        title="Only Thread",
        format="Comic",
        status="active",
        queue_position=1,
        user_id=user.id,
    )
    db.add(thread)
    db.commit()

    move_to_position(thread.id, user.id, 5, db)

    thread = db.get(Thread, thread.id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_user_cannot_move_other_users_threads(auth_client, db) -> None:
    """User A cannot move User B's threads."""
    from app.models import User

    user_a = User(username="user_a", created_at=datetime.now(UTC))
    db.add(user_a)
    user_b = User(username="user_b", created_at=datetime.now(UTC))
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    from app.auth import create_access_token

    token_b = create_access_token(data={"sub": user_b.username, "jti": "test"})
    auth_client.headers.update({"Authorization": f"Bearer {token_b}"})

    thread_a = Thread(
        title="User A Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user_a.id,
        created_at=datetime.now(UTC),
    )
    db.add(thread_a)
    db.commit()

    response = await auth_client.put(
        f"/api/queue/threads/{thread_a.id}/position/",
        json={"new_position": 5},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_roll_pool_isolated_per_user(db) -> None:
    """get_roll_pool returns only user's own threads."""
    from app.models import User

    user_a = User(username="user_a", created_at=datetime.now(UTC))
    db.add(user_a)
    user_b = User(username="user_b", created_at=datetime.now(UTC))
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    thread_a = Thread(
        title="User A Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user_a.id,
        created_at=datetime.now(UTC),
    )
    thread_b = Thread(
        title="User B Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user_b.id,
        created_at=datetime.now(UTC),
    )
    db.add_all([thread_a, thread_b])
    db.commit()

    roll_pool_a = get_roll_pool(user_a.id, db)
    assert len(roll_pool_a) == 1
    assert roll_pool_a[0].id == thread_a.id

    roll_pool_b = get_roll_pool(user_b.id, db)
    assert len(roll_pool_b) == 1
    assert roll_pool_b[0].id == thread_b.id


@pytest.mark.asyncio
async def test_get_stale_threads_isolated_per_user(db) -> None:
    """get_stale_threads returns only user's own stale threads."""
    from app.models import User

    user_a = User(username="user_a", created_at=datetime.now(UTC))
    db.add(user_a)
    user_b = User(username="user_b", created_at=datetime.now(UTC))
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    stale_thread_a = Thread(
        title="Stale User A Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        last_activity_at=datetime.now(UTC) - timedelta(days=10),
        user_id=user_a.id,
        created_at=datetime.now(UTC),
    )
    stale_thread_b = Thread(
        title="Stale User B Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        last_activity_at=datetime.now(UTC) - timedelta(days=10),
        user_id=user_b.id,
        created_at=datetime.now(UTC),
    )
    db.add_all([stale_thread_a, stale_thread_b])
    db.commit()

    stale_threads_a = get_stale_threads(user_a.id, db, days=7)
    assert len(stale_threads_a) == 1
    assert stale_threads_a[0].id == stale_thread_a.id

    stale_threads_b = get_stale_threads(user_b.id, db, days=7)
    assert len(stale_threads_b) == 1
    assert stale_threads_b[0].id == stale_thread_b.id


@pytest.mark.asyncio
async def test_move_to_position_respects_user_isolation(db) -> None:
    """move_to_position only affects user's own threads."""
    from app.models import User

    user_a = User(username="user_a", created_at=datetime.now(UTC))
    db.add(user_a)
    user_b = User(username="user_b", created_at=datetime.now(UTC))
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    thread_a1 = Thread(
        title="User A Thread 1",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=user_a.id,
        created_at=datetime.now(UTC),
    )
    thread_a2 = Thread(
        title="User A Thread 2",
        format="Comic",
        issues_remaining=5,
        queue_position=2,
        status="active",
        user_id=user_a.id,
        created_at=datetime.now(UTC),
    )
    thread_b1 = Thread(
        title="User B Thread 1",
        format="Comic",
        issues_remaining=8,
        queue_position=1,
        status="active",
        user_id=user_b.id,
        created_at=datetime.now(UTC),
    )
    thread_b2 = Thread(
        title="User B Thread 2",
        format="Comic",
        issues_remaining=3,
        queue_position=2,
        status="active",
        user_id=user_b.id,
        created_at=datetime.now(UTC),
    )
    db.add_all([thread_a1, thread_a2, thread_b1, thread_b2])
    db.commit()

    move_to_position(thread_a2.id, user_a.id, 1, db)

    db.refresh(thread_a1)
    db.refresh(thread_a2)
    db.refresh(thread_b1)
    db.refresh(thread_b2)

    assert thread_a2.queue_position == 1
    assert thread_a1.queue_position == 2
    assert thread_b1.queue_position == 1
    assert thread_b2.queue_position == 2
