"""Performance regression test for undo endpoint query count.

Ensures the undo endpoint builds its response with pre-computed values
instead of re-querying session, die, ladder path, and snapshot count after commit.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from httpx import AsyncClient

from app.models import Event, Snapshot, Thread
from app.models import Session as SessionModel
from app.services.snapshot_contract import SNAPSHOT_VERSION, SNAPSHOT_VERSION_KEY


@pytest.mark.asyncio
async def test_undo_endpoint_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Ensure undo endpoint uses a bounded number of DB queries.

    The optimized implementation:
    - Uses get_current_die_for_session to avoid re-querying the session.
    - Pre-computes active thread, ladder path, and snapshot count before commit.
    - Skips db.refresh(session) after commit.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    # Create a session with a pending thread.
    session = SessionModel(start_die=6, user_id=user.id)
    async_db.add(session)
    await async_db.flush()

    thread = Thread(
        title="Perf Undo Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()

    # Create a roll event.
    roll_event = Event(
        type="roll",
        die=6,
        result=1,
        selected_thread_id=thread.id,
        selection_method="random",
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(roll_event)
    await async_db.flush()

    # Create a rate event and delta snapshot.
    rate_event = Event(
        type="rate",
        rating=4.5,
        issues_read=1,
        die=6,
        die_after=4,
        session_id=session.id,
        thread_id=thread.id,
    )
    async_db.add(rate_event)
    await async_db.flush()

    snapshot = Snapshot(
        session_id=session.id,
        event_id=rate_event.id,
        thread_states={
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            str(thread.id): {
                "title": thread.title,
                "format": thread.format,
                "issues_remaining": thread.issues_remaining,
                "last_rating": thread.last_rating,
                "queue_position": thread.queue_position,
                "status": thread.status,
                "is_test": thread.is_test,
                "is_blocked": thread.is_blocked,
                "created_at": thread.created_at.isoformat(),
                "user_id": thread.user_id,
                SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            },
        },
        session_state={
            "start_die": session.start_die,
            "manual_die": session.manual_die,
            "current_die": 4,
        },
        description="After rating",
    )
    async_db.add(snapshot)
    await async_db.commit()

    # Undo the snapshot.
    undo_resp = await auth_client.post(
        f"/api/v1/undo/{session.id}/undo/{snapshot.id}",
    )
    assert undo_resp.status_code == 200

    queries = int(undo_resp.headers.get("X-App-DB-Queries", "0"))
    # Before optimization: ~15-25 queries. After: should be well under 15.
    assert queries <= 14, f"Too many DB queries on undo: {queries}"
