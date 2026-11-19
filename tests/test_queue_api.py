"""Tests for queue API endpoints."""

from datetime import datetime, UTC

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession

from app.models import User


@pytest.mark.parametrize(
    "method,path",
    [
        ("put", "/api/v1/queue/threads/1/position/"),
        ("put", "/api/v1/queue/threads/1/back/"),
        ("post", "/api/v1/queue/shuffle/"),
        ("put", "/api/queue/threads/1/position/"),
        ("put", "/api/queue/threads/1/back/"),
        ("post", "/api/queue/shuffle/"),
    ],
)
async def test_retired_queue_action_routes_answer_404(
    auth_client: AsyncClient, method: str, path: str
) -> None:
    """Retired v1/bare queue actions return 404; v2 resources are the replacement.

    The native queue-entry resource (``PATCH /api/v2/queue-entries/{thread_id}``
    with a target ``position`` for front/middle/back, and ``POST
    /api/v2/queue-orders`` for shuffle) owns ordering, reorder/shuffle audit
    events, idempotency, and owner isolation in Rust. Python must not
    re-register the action-shaped routes, so a request here falls through to
    the JSON 404 fallback instead of moving a queue.
    """
    kwargs = {"json": {"new_position": 1}} if path.endswith("/position/") else {}
    response = await getattr(auth_client, method)(path, **kwargs)
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
