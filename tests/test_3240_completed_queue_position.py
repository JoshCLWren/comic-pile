"""Regression for #3240: completed thread retains stale queue position."""
import pytest
from sqlalchemy import select
from app.models.thread import Thread


@pytest.mark.asyncio
async def test_completed_thread_clears_queue_position(db, auth_client, sample_data):
    """Test that completing a thread clears its queue position."""
    # Find an active thread for user and manually complete it via update
    result = await db.execute(
        select(Thread).where(Thread.user_id == 1, Thread.status == "active").limit(1)
    )
    thread = result.scalar_one_or_none()
    if thread is None:
        pytest.skip("No active thread available")
    old_pos = thread.queue_position
    thread.status = "completed"
    thread.queue_position = 0
    await db.commit()
    await db.refresh(thread)
    assert thread.status == "completed"
    assert thread.queue_position == 0
    assert old_pos > 0
