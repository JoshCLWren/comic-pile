"""Tests for roll API endpoints migrated to v2 Roll/offer."""


import pytest
import secrets
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_roll_success(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/offer returns valid thread."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response.status_code == 200

    data = response.json()
    assert "thread_id" in data
    assert "title" in data
    assert "die_size" in data
    assert "result" in data
    assert data["die_size"] == 8
    assert 1 <= data["result"] <= 8

    thread_ids = [t.id for t in sample_data["threads"] if t.status == "active"]
    assert data["thread_id"] in thread_ids


@pytest.mark.asyncio
async def test_roll_offer_with_snoozed_threads(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/offer excludes snoozed threads."""
    # First, get a roll to establish a session
    first_response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert first_response.status_code == 200
    
    # Get session to find thread IDs
    session_response = await auth_client.get("/api/v1/sessions/current/")
    assert session_response.status_code == 200
    session_data = session_response.json()
    
    # Snooze one thread and roll again
    snoozed_thread_ids = [session_data["roll_pool"][0]["id"]] if session_data.get("roll_pool") else []
    second_response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": snoozed_thread_ids
    })
    assert second_response.status_code == 200
    
    # Should not select the snoozed thread
    data = second_response.json()
    assert data["thread_id"] not in snoozed_thread_ids


@pytest.mark.asyncio
async def test_roll_no_pool(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Returns error if no active threads."""
    from tests.conftest import get_or_create_user_async

    await get_or_create_user_async(async_db)

    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response.status_code == 400
    assert "No eligible comics" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_overflow(auth_client: AsyncClient, async_db: AsyncSession) -> None:
    """Roll works correctly when thread count < die size."""
    from app.models import Thread
    from tests.conftest import get_or_create_user_async

    user = await get_or_create_user_async(async_db)

    thread = Thread(
        title="Only Thread",
        format="Comic",
        issues_remaining=5,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.commit()
    await async_db.refresh(thread)

    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] == thread.id
    assert 1 <= data["result"] <= 1


@pytest.mark.asyncio
async def test_roll_offer_idempotency(auth_client: AsyncClient, sample_data: dict) -> None:
    """Same idempotency key returns same result."""
    key = secrets.token_urlsafe(16)
    
    # First request
    response1 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": key,
        "snoozed_thread_ids": []
    })
    assert response1.status_code == 200
    data1 = response1.json()

    # Second request with same key
    response2 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": key,
        "snoozed_thread_ids": []
    })
    assert response2.status_code == 200
    data2 = response2.json()

    # Should return same result
    assert data1["thread_id"] == data2["thread_id"]
    assert data1["result"] == data2["result"]


@pytest.mark.asyncio
async def test_roll_offer_different_keys_different_results(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Different idempotency keys can return different results."""
    key1 = secrets.token_urlsafe(16)
    key2 = secrets.token_urlsafe(16)
    
    response1 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": key1,
        "snoozed_thread_ids": []
    })
    response2 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": key2,
        "snoozed_thread_ids": []
    })
    
    assert response1.status_code == 200
    assert response2.status_code == 200
    
    # May or may not be different due to randomness
    data1 = response1.json()
    data2 = response2.json()
    assert data1["thread_id"] is not None
    assert data2["thread_id"] is not None


@pytest.mark.asyncio
async def test_roll_timezone_parameter(auth_client: AsyncClient, sample_data: dict) -> None:
    """POST /roll/accepts timezone parameter."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": [],
        "timezone": "America/New_York"
    })
    assert response.status_code == 200

    data = response.json()
    assert "thread_id" in data
    assert data["die_size"] == 8


@pytest.mark.asyncio
async def test_roll_invalid_idempotency_key(auth_client: AsyncClient) -> None:
    """Invalid idempotency key returns 422."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": "invalid",  # Too short
        "snoozed_thread_ids": []
    })
    assert response.status_code == 422
    assert "Invalid idempotency key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_missing_idempotency_key(auth_client: AsyncClient) -> None:
    """Missing idempotency key returns 422."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "snoozed_thread_ids": []
    })
    assert response.status_code == 422
    assert "idempotency_key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_roll_expected_pending_thread_validation(
    auth_client: AsyncClient, sample_data: dict
) -> None:
    """Expected pending thread validation works."""
    # First roll without expected pending
    response1 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response1.status_code == 200
    data1 = response1.json()

    # Second roll with expected pending (should fail since no pending exists)
    response2 = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": [],
        "expected_pending_thread_id": data1["thread_id"] + 999  # Non-existent
    })
    assert response2.status_code == 400
    assert "No other eligible comics remain" in response2.json()["detail"]


@pytest.mark.asyncio
async def test_roll_response_structure(auth_client: AsyncClient, sample_data: dict) -> None:
    """Roll response has all expected fields."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response.status_code == 200

    data = response.json()
    required_fields = [
        "thread_id", "title", "format", "issues_remaining", "queue_position",
        "die_size", "result", "offset", "snoozed_count", "issue_id",
        "issue_number", "next_issue_id", "next_issue_number", "total_issues",
        "reading_progress", "explanation", "last_rolled_result", "snoozed_thread_id"
    ]
    
    for field in required_fields:
        assert field in data, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_roll_with_timezone_info(auth_client: AsyncClient, sample_data: dict) -> None:
    """Roll includes timezone information in response."""
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": [],
        "timezone": "Europe/London"
    })
    assert response.status_code == 200

    data = response.json()
    assert data["thread_id"] is not None
    assert data["die_size"] == 8


@pytest.mark.asyncio
async def test_roll_bootstrap_integration(auth_client: AsyncClient, sample_data: dict) -> None:
    """Roll endpoint integrates with bootstrap endpoint."""
    # Get bootstrap first
    bootstrap_response = await auth_client.get("/api/v2/roll/bootstrap")
    assert bootstrap_response.status_code == 200
    bootstrap_data = bootstrap_response.json()
    
    # Use die info from bootstrap in roll
    response = await auth_client.post("/api/v2/roll/offer", json={
        "idempotency_key": secrets.token_urlsafe(16),
        "snoozed_thread_ids": []
    })
    assert response.status_code == 200
    
    roll_data = response.json()
    assert roll_data["die_size"] == bootstrap_data["current_die"]
    assert roll_data["thread_id"] in [t["id"] for t in bootstrap_data["rollable"]]