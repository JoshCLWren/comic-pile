"""Performance regression test for snooze endpoint query count."""

import pytest

@pytest.mark.asyncio
async def test_snooze_endpoint_query_count(auth_client, async_db):
    """Ensure snooze endpoint uses a bounded number of DB queries (≤10)."""
    # Ensure we have an active session and pending thread via roll.
    roll_resp = await auth_client.post("/api/roll/")
    assert roll_resp.status_code == 200

    snooze_resp = await auth_client.post("/api/snooze/")
    assert snooze_resp.status_code == 200

    queries = int(snooze_resp.headers.get("X-App-DB-Queries", "0"))
    assert queries <= 10, f"Too many DB queries on snooze: {queries}"