"""Performance regression test for snooze endpoint query count.

Ensures the snooze endpoint builds its snoozed-thread list with a single
bulk query instead of one query per snoozed thread (N+1 loop).
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from httpx import AsyncClient

from app.models import Session, Thread


@pytest.mark.asyncio
async def test_snooze_endpoint_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Ensure snooze endpoint uses a bounded number of DB queries (<=10)."""
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    session = Session(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.commit()
    await async_db.refresh(session)

    thread = Thread(
        title="Perf Snooze Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Create a roll event to set up pending_thread_id.
    from app.models import Event

    event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(event)
    session.pending_thread_id = thread.id
    await async_db.commit()

    snooze_resp = await auth_client.post("/api/snooze/")
    assert snooze_resp.status_code == 200

    queries = int(snooze_resp.headers.get("X-App-DB-Queries", "0"))
    assert queries <= 10, f"Too many DB queries on snooze: {queries}"
