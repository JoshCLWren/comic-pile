"""Performance regression test for snooze endpoint query count.

Ensures the snooze endpoint builds its response with pre-computed values
instead of re-querying session, die, ladder path, and snapshot count after commit.
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
    """Ensure snooze endpoint uses a bounded number of DB queries.

    The optimized implementation:
    - Uses get_current_die_for_session to avoid re-querying the session.
    - Pre-computes active thread, ladder path, and snapshot count before commit.
    - Passes pre-computed values to build_session_response to skip post-commit queries.
    """
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
    # Before optimization: ~12-18 queries. After: should be well under 12.
    assert queries <= 10, f"Too many DB queries on snooze: {queries}"
