"""Regression for #3763: cancelling a pending roll is recorded in History.

A dismissal is reading activity, so the session timeline must show it as a
classified entry instead of leaving the cancellation silently absent.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Event


@pytest.mark.asyncio
async def test_dismiss_pending_records_a_classified_dismiss_event(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Cancelling a pending roll records one dismiss event for that series."""
    _ = sample_data

    roll_response = await auth_client.post("/api/v1/roll/")
    assert roll_response.status_code == 200
    rolled_thread_id = roll_response.json()["thread_id"]
    rolled_title = roll_response.json()["title"]

    current = await auth_client.get("/api/v1/sessions/current/")
    assert current.status_code == 200
    session_id = current.json()["id"]

    dismiss_response = await auth_client.post("/api/v1/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    stored = (
        (
            await async_db.execute(
                select(Event).where(
                    Event.session_id == session_id, Event.type == "dismiss"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(stored) == 1
    assert stored[0].selected_thread_id == rolled_thread_id

    details = await auth_client.get(f"/api/v1/sessions/{session_id}/details")
    assert details.status_code == 200
    dismiss_event = next(
        event for event in details.json()["events"] if event["type"] == "dismiss"
    )
    assert dismiss_event["thread_title"] == rolled_title
    assert dismiss_event["description"] == f"Dismissed {rolled_title}"
    assert rolled_title in details.json()["narrative_summary"]["skipped"]


@pytest.mark.asyncio
async def test_dismiss_pending_without_pending_records_no_event(
    auth_client: AsyncClient, async_db: AsyncSession, sample_data: dict
) -> None:
    """Cancelling when nothing is pending stays a no-op."""
    _ = sample_data

    current = await auth_client.get("/api/v1/sessions/current/")
    assert current.status_code == 200
    session_id = current.json()["id"]

    dismiss_response = await auth_client.post("/api/v1/roll/dismiss-pending")
    assert dismiss_response.status_code == 204

    stored = (
        (
            await async_db.execute(
                select(Event).where(
                    Event.session_id == session_id, Event.type == "dismiss"
                )
            )
        )
        .scalars()
        .all()
    )
    assert stored == []
