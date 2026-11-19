"""Regression tests for #3467: double-clicked manual picks log one event.

Double-clicking "Pick this series" submits the same override twice before the
button's disabled state re-renders. The override endpoint must record a single
ROLLED event when an override immediately repeats the session's newest
override for the same series, while still letting any later, distinct pick
log its own event.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event


async def _override_event_count(async_db: AsyncSession, thread_id: int) -> int:
    result = await async_db.execute(
        select(func.count())
        .select_from(Event)
        .where(Event.type == "roll")
        .where(Event.selection_method == "override")
        .where(Event.selected_thread_id == thread_id)
    )
    return int(result.scalar_one())


@pytest.mark.asyncio
async def test_repeat_override_logs_single_event(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """Two identical override posts record exactly one ROLLED event."""
    thread_id = sample_data["threads"][0].id

    first = await auth_client.post("/api/v1/roll/override", json={"thread_id": thread_id})
    assert first.status_code == 200, first.text
    assert first.json()["thread_id"] == thread_id

    second = await auth_client.post("/api/v1/roll/override", json={"thread_id": thread_id})
    assert second.status_code == 200, second.text
    assert second.json()["thread_id"] == thread_id

    assert await _override_event_count(async_db, thread_id) == 1


@pytest.mark.asyncio
async def test_distinct_picks_still_log_new_events(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    sample_data: dict,
) -> None:
    """A different pick is the newest event, so re-picking logs a new event."""
    thread_one = sample_data["threads"][0].id
    thread_two = sample_data["threads"][1].id

    for thread_id in (thread_one, thread_two, thread_one):
        response = await auth_client.post(
            "/api/v1/roll/override", json={"thread_id": thread_id}
        )
        assert response.status_code == 200, response.text

    assert await _override_event_count(async_db, thread_one) == 2
    assert await _override_event_count(async_db, thread_two) == 1
