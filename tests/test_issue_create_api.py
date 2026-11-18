"""Tests for Issue Create API endpoints."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from tests.conftest import get_or_create_user_async








async def test_create_issues_thread_not_found(auth_client: AsyncClient) -> None:
    """POST /threads/{thread_id}/issues returns 404 for non-existent thread."""
    response = await auth_client.post("/api/v1/threads/999/issues", json={"issue_range": "1-5"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()





async def test_create_issues_insert_after_issue_requires_issue_in_same_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues rejects insert_after_issue_id from another thread."""
    user = await get_or_create_user_async(async_db)

    target_thread = Thread(
        title="Target Thread",
        format="Comic",
        issues_remaining=2,
        queue_position=1,
        status="active",
        user_id=user.id,
        total_issues=2,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    other_thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=1,
        queue_position=2,
        status="active",
        user_id=user.id,
        total_issues=1,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([target_thread, other_thread])
    await async_db.flush()

    target_issues = [
        Issue(thread_id=target_thread.id, issue_number="1", position=1, status="unread"),
        Issue(thread_id=target_thread.id, issue_number="2", position=2, status="unread"),
    ]
    other_issue = Issue(thread_id=other_thread.id, issue_number="1", position=1, status="unread")
    async_db.add_all([*target_issues, other_issue])
    await async_db.flush()

    target_thread.next_unread_issue_id = target_issues[0].id
    other_thread.next_unread_issue_id = other_issue.id
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{target_thread.id}/issues",
        json={"issue_range": "Annual 1", "insert_after_issue_id": other_issue.id},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    result = await async_db.execute(
        select(Issue).where(Issue.thread_id == target_thread.id).order_by(Issue.position)
    )
    issues_in_order = result.scalars().all()
    assert [issue.issue_number for issue in issues_in_order] == ["1", "2"]
    assert [issue.position for issue in issues_in_order] == [1, 2]

    await async_db.refresh(target_thread)
    assert target_thread.total_issues == 2
    assert target_thread.issues_remaining == 2
    assert target_thread.next_unread_issue_id == target_issues[0].id


async def test_create_issues_other_user_thread(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /threads/{thread_id}/issues returns 404 for thread owned by different user."""
    other_user = User(username="other_user", created_at=datetime.now(UTC))
    async_db.add(other_user)
    await async_db.commit()

    thread = Thread(
        title="Other Thread",
        format="Comic",
        issues_remaining=10,
        queue_position=1,
        status="active",
        user_id=other_user.id,
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.commit()

    response = await auth_client.post(
        f"/api/v1/threads/{thread.id}/issues", json={"issue_range": "1-5"}
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()













@contextmanager
def _captured_statements(db_engine: AsyncEngine) -> Iterator[list[str]]:
    """Yield a list that records all SQL statements executed on the engine."""
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(str(statement))

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        yield statements
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)


async def _make_thread_with_comicvine_mapping(
    async_db: AsyncSession,
    *,
    user_id: int,
    title: str = "Starman",
    volume_id: str = "12345",
    existing_numbers: list[str] | None = None,
) -> Thread:
    """Create a thread with a confirmed ComicVine series mapping and optional issues."""
    from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping

    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=3,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()

    series_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=volume_id,
        metadata_json={"name": title, "count_of_issues": 100},
    )
    async_db.add(series_identity)
    await async_db.flush()

    mapping = ThreadExternalSeriesMapping(
        thread_id=thread.id,
        external_identity_id=series_identity.id,
        status="confirmed",
        evidence_source="user_series_confirmation",
        confidence=1.0,
    )
    async_db.add(mapping)

    if existing_numbers:
        issues = [
            Issue(thread_id=thread.id, issue_number=num, position=idx + 1, status="read")
            for idx, num in enumerate(existing_numbers)
        ]
        async_db.add_all(issues)
        await async_db.flush()
        thread.next_unread_issue_id = None
        await async_db.flush()

    await async_db.commit()
    return thread


def _mock_comicvine_client(mocker, volume_issues: list[dict]) -> None:
    """Mock the ComicVine client for volume listing and issue hydration."""
    mocker.patch.dict("os.environ", {"COMICVINE_API_KEY": "test-key"})
    from comic_pile.comicvine_provider import ComicVineResponse

    mock_client = mocker.AsyncMock()
    mock_client.fetch_volume_issues.return_value = volume_issues
    mock_client.fetch_issue.return_value = ComicVineResponse(
        payload={
            "results": {
                "id": 99999,
                "issue_number": "1",
                "name": "Issue 1",
                "site_detail_url": "https://example.com/issue/99999/",
                "date_last_updated": "2026-01-01T00:00:00",
            }
        },
        from_cache=False,
        cache_key="fake",
    )
    mocker.patch("app.services.issue.ComicVineClient", return_value=mock_client)
    mocker.patch("app.comicvine_hydration.ComicVineClient", return_value=mock_client)




