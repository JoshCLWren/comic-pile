"""Regression tests for batch blocking-info request normalization."""

import pytest
from sqlalchemy import select

from app.models import Thread, User


@pytest.mark.asyncio
async def test_batch_blocking_info_deduplicates_thread_ids(
    auth_client,
    async_db,
    test_username,
) -> None:
    """Duplicate owned IDs should not fail the ownership-count validation."""
    user_result = await async_db.execute(select(User).where(User.username == test_username))
    user = user_result.scalar_one()

    thread = Thread(
        title="Duplicate Batch Target",
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=1,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post(
        "/api/v1/threads:getBlockingInfo",
        json={"thread_ids": [thread.id, thread.id, thread.id]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "threads": {
            str(thread.id): {
                "is_blocked": False,
                "blocking_reasons": [],
            }
        }
    }
