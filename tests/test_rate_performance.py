"""Performance regression test for rate endpoint round-trip count.

Ensures the rate endpoint performs a bounded number of DB queries after optimization.
"""

import pytest

@pytest.mark.asyncio
async def test_rate_endpoint_query_count(auth_client, async_db):
    """Check that the rate endpoint uses ≤10 DB queries.

    The optimized implementation avoids an extra SELECT after commit.
    """
    # Establish a session and pending thread via a roll.
    roll_resp = await auth_client.post("/api/roll/")
    assert roll_resp.status_code == 200

    # Rate the thread.
    rate_resp = await auth_client.post(
        "/api/rate/",
        json={"rating": 4.0, "issues_read": 1},
    )
    assert rate_resp.status_code == 200

    queries = int(rate_resp.headers.get("X-App-DB-Queries", "0"))
    assert queries <= 10, f"Too many DB queries: {queries}"