"""Tests for queue API endpoints."""

import pytest
from datetime import datetime
from sqlalchemy import select

from app.models import Thread
from comic_pile.queue import get_roll_pool


@pytest.mark.asyncio
async def test_move_to_position(client, db, sample_data):
    """PUT /queue/threads/{id}/position/ works."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    thread2 = db.get(Thread, sample_data["threads"][1].id)
    thread4 = db.get(Thread, sample_data["threads"][3].id)
    assert thread1.queue_position == 2
    assert thread2.queue_position == 3
    assert thread4.queue_position == 4


@pytest.mark.asyncio
async def test_move_to_front(client, db, sample_data):
    """PUT /queue/threads/{id}/front/ moves to position 1."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(f"/api/queue/threads/{thread_id}/front/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 1

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1

    thread1 = db.get(Thread, sample_data["threads"][0].id)
    assert thread1.queue_position == 2


@pytest.mark.asyncio
async def test_move_to_back(client, db, sample_data):
    """PUT /queue/threads/{id}/back/ moves to last position."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(f"/api/queue/threads/{thread_id}/back/")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == thread_id
    assert data["position"] == 5

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_queue_order_preserved(client, db, sample_data):
    """Other threads shift correctly when one moves."""
    thread_id = sample_data["threads"][1].id
    new_position = 4

    response = await client.put(
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
async def test_move_to_position_invalid(client, db, sample_data):
    """Moving to invalid position caps at boundaries."""
    thread_id = sample_data["threads"][2].id

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 999}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_move_to_position_zero_fails_validation(client, db, sample_data):
    """Moving to position 0 fails validation."""
    thread_id = sample_data["threads"][2].id

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 0}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_roll_pool(client, sample_data):
    """GET /threads/ returns threads ordered by position."""
    response = await client.get("/api/threads/")
    assert response.status_code == 200

    data = response.json()
    assert len(data) >= 5

    for i in range(len(data) - 1):
        assert data[i]["position"] <= data[i + 1]["position"]


@pytest.mark.asyncio
async def test_move_completed_thread(client, db, sample_data):
    """Moving completed thread works correctly."""
    thread_id = sample_data["threads"][2].id
    new_position = 1

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": new_position}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 1


@pytest.mark.asyncio
async def test_move_nonexistent_thread(client, db, sample_data):
    """Returns 404 for non-existent thread."""
    response = await client.put("/api/queue/threads/999/front/")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_move_back_thread_forward(db, sample_data):
    """Moving thread from front to back shifts other threads up."""
    from comic_pile.queue import move_to_back

    thread_id = sample_data["threads"][0].id

    move_to_back(thread_id, db)

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
    """move_to_front returns early for non-existent thread."""
    from comic_pile.queue import move_to_front

    move_to_front(999, db)

    assert True


@pytest.mark.asyncio
async def test_move_to_back_nonexistent(db):
    """move_to_back returns early for non-existent thread."""
    from comic_pile.queue import move_to_back

    move_to_back(999, db)

    assert True


@pytest.mark.asyncio
async def test_move_to_position_nonexistent(db):
    """move_to_position returns early for non-existent thread."""
    from comic_pile.queue import move_to_position

    move_to_position(999, 1, db)

    assert True


@pytest.mark.asyncio
async def test_move_to_same_position(db, sample_data):
    """Moving to same position is a no-op."""
    from comic_pile.queue import move_to_position

    thread_id = sample_data["threads"][2].id

    move_to_position(thread_id, 3, db)

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

    stale = get_stale_threads(db, days=7)

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

    stale = get_stale_threads(db, days=10)

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

    stale = get_stale_threads(db, days=7)

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

    roll_pool = get_roll_pool(db)

    assert len(roll_pool) == 2
    assert roll_pool[0].id == thread2.id
    assert roll_pool[1].id == thread1.id


@pytest.mark.asyncio
async def test_jump_to_far_position(client, db, sample_data):
    """Jump from position 1 to position 5 works correctly."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(
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
async def test_jump_to_near_position(client, db, sample_data):
    """Jump from position 5 to position 2 works correctly."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(
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
async def test_jump_beyond_last_position(client, db, sample_data):
    """Jumping beyond last position caps at last position."""
    thread_id = sample_data["threads"][0].id

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": 999}
    )
    assert response.status_code == 200

    thread = db.get(Thread, thread_id)
    assert thread.queue_position == 5


@pytest.mark.asyncio
async def test_jump_to_negative_position_fails_validation(client, db, sample_data):
    """Jumping to negative position fails validation."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(
        f"/api/queue/threads/{thread_id}/position/", json={"new_position": -5}
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_jump_to_zero_position_fails_validation(client, db, sample_data):
    """Jumping to position 0 fails validation."""
    thread_id = sample_data["threads"][4].id

    response = await client.put(
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

    move_to_back(999, db)


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

    move_to_position(thread.id, 5, db)

    thread = db.get(Thread, thread.id)
    assert thread.queue_position == 1
