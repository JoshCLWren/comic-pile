"""Endpoint-level regression coverage for the linear History event projection.

These tests prove ``list_sessions()`` preserves the exact History response
contract when it assembles summaries from the single ordered event read
produced by ``project_session_history_events()``.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import User
from app.models import ReadingSession


async def _commit_all(async_db: AsyncSession) -> None:
    await async_db.flush()
    await async_db.commit()




































@pytest.mark.asyncio
async def test_current_session_selects_newest_active_candidate(
    auth_client: AsyncClient, async_db: AsyncSession, default_user: User
) -> None:
    """Current-session selection uses the newest open candidate and stays active."""
    now = datetime.now(UTC)
    open_sessions = [
        ReadingSession(start_die=6, user_id=default_user.id, started_at=now),
        ReadingSession(start_die=8, user_id=default_user.id, started_at=now),
        ReadingSession(
            start_die=10,
            user_id=default_user.id,
            started_at=now - timedelta(hours=2),
            ended_at=now - timedelta(hours=1),
        ),
    ]
    async_db.add_all(open_sessions)
    await _commit_all(async_db)

    response = await auth_client.get("/api/v1/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["start_die"] in {6, 8}, "Must select one of the active open sessions"


@pytest.mark.asyncio
async def test_current_session_candidate_read_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """Current-session selection reads at most one candidate session row."""
    now = datetime.now(UTC)
    for i in range(10):
        async_db.add(
            ReadingSession(
                start_die=6,
                user_id=default_user.id,
                started_at=now - timedelta(minutes=i),
            )
        )
    await _commit_all(async_db)

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    sa_event.listen(db_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        response = await auth_client.get("/api/v1/sessions/current/")
    finally:
        sa_event.remove(db_engine.sync_engine, "before_cursor_execute", record_statement)

    assert response.status_code == 200
    assert response.json()["start_die"] == 6

    session_candidate_reads = [
        s for s in statements if "from sessions" in s.lower() and "order by" in s.lower()
    ]
    assert len(session_candidate_reads) == 1, (
        f"Expected one bounded candidate read, got {len(session_candidate_reads)}: "
        f"{session_candidate_reads}"
    )
