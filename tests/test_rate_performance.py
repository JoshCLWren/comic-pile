"""Performance regression test for rate endpoint round-trip count.

Ensures the rate endpoint performs a bounded number of DB queries after
removing redundant post-commit re-reads and using get_current_die_for_session.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from httpx import AsyncClient

from app.models import Thread


@pytest.mark.asyncio
async def test_rate_endpoint_query_count(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Check that the rate endpoint uses a bounded number of DB queries.

    The optimized implementation reuses the already-loaded session and thread
    objects instead of issuing extra SELECTs after commit. Key savings:
    - get_current_die_for_session avoids re-querying the session object.
    - Pre-extracting response values avoids db.refresh(thread) after commit.
    - Building ThreadResponse directly avoids thread_to_response's extra queries.
    """
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)
    thread = Thread(
        title="Perf Rate Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    # Establish a session and pending thread via a roll.
    roll_resp = await auth_client.post("/api/v1/roll/")
    assert roll_resp.status_code == 200

    # Rate the thread.
    rate_resp = await auth_client.post(
        "/api/v1/rate/",
        json={"rating": 4.0},
    )
    assert rate_resp.status_code == 200

    queries = int(rate_resp.headers.get("X-App-DB-Queries", "0"))
    # Before optimization: ~15-25 queries. After: should be well under 15.
    assert queries <= 12, f"Too many DB queries: {queries}"
