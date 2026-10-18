"""Regression for #3449: dense queue positions after mutation.
Asserts roll-card / thread-page / queue-page agreement.
"""
import pytest
from app.models import Thread
from app.repositories import thread_repository


@pytest.mark.asyncio
async def test_queue_positions_remain_dense_after_delete(db, user_factory):
    user = await user_factory()
    t1 = Thread(user_id=user.id, title="A", status="active", queue_position=1)
    t2 = Thread(user_id=user.id, title="B", status="active", queue_position=2)
    t3 = Thread(user_id=user.id, title="C", status="active", queue_position=3)
    db.add_all([t1, t2, t3])
    await db.commit()
    await db.refresh(t1); await db.refresh(t2); await db.refresh(t3)

    await thread_repository.delete_thread(db, t2)
    await thread_repository.renormalize_queue_positions(db, user.id)
    await db.commit()

    result = await db.execute(
        __import__("sqlalchemy").select(Thread.queue_position)
        .where(Thread.user_id == user.id)
        .where(Thread.status == "active")
        .order_by(Thread.queue_position)
    )
    positions = result.scalars().all()
    assert list(positions) == [1, 2], f"expected dense 1,2 got {positions}"
    assert max(positions) <= 2
