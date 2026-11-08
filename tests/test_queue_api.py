"""Tests for queue API endpoints."""

from datetime import datetime, UTC

from httpx import AsyncClient
import pytest
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession

from app.models import User


@pytest.mark.asyncio
async def test_create_threads_to_meet_20(
    auth_client: AsyncClient, async_db: SQLAlchemyAsyncSession
) -> None:
    """Create threads 18-20 programmatically."""
    # Setup: Ensure user exists and related threads match context
    user = await async_db.execute(select(User).where(User.username == "test_user"))
    user = user.scalar_one_or_none()
    if not user:
        user = User(username="test_user", created_at=datetime.now(UTC), id=123)
        async_db.add(user)
        await async_db.commit()
        await async_db.refresh(user)
    threads_data = [
        {
            "title": "Arrow Reborn",
            "format": "Mini Series",
            "issues_remaining": 6,
            "notes": "Star City's finest archer returns.",
        },
        {
            "title": "Justice Society Revival",
            "format": "Anthology",
            "issues_remaining": 19,
            "notes": "Golden Age heroes unite.",
        },
        {
            "title": "Custom Thread 20",
            "format": "One-Shot",
            "issues_remaining": 1,
            "notes": "Final placeholder thread",
        },
    ]

    for thread in threads_data:
        resp = await auth_client.post("/api/v1/threads/", json=thread)
        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["title"] == thread["title"]


