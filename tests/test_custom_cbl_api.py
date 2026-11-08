"""Pruned custom-CBL CRUD: browser uses v2 reading-lists; live endpoints remain."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue, Thread

from app.main import create_app


@pytest.mark.asyncio
async def test_custom_cbl_crud_is_pruned(auth_client: AsyncClient) -> None:
    """Bare custom-CBL CRUD and reader/overlap handlers are gone; live search/export/apply remain."""
    assert (await auth_client.get("/api/v1/custom-cbls")).status_code == 404
    assert (await auth_client.post("/api/v1/custom-cbls", json={})).status_code == 404
    assert (await auth_client.get("/api/v1/custom-cbls/123")).status_code == 404
    assert (await auth_client.get("/api/v1/custom-cbls/123/reader")).status_code == 404
    schema = create_app(serve_frontend=False).openapi()
    assert "/api/v1/custom-cbls/issue-search" in schema["paths"]
    assert "/api/v1/custom-cbls/{list_id}/export" in schema["paths"]
    assert "/api/v1/custom-cbls/{list_id}/reading-plans/{plan_id}:apply" in schema["paths"]
    assert "/api/v1/custom-cbls/{list_id}/reader" not in schema["paths"]


async def _issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    issue_number: str,
    queue_position: int,
) -> Issue:
    """Create one canonical owned issue in its real thread (shared test helper)."""
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    return issue
