"""Exclusion transparency for issue #3125: every non-rollable series is explained.

These tests drive the real endpoint against the async PostgreSQL fixture so the
availability predicates are exercised against real rows instead of query-order
doubles. ``is_blocked``, ``status``, and ``queue_position`` all feed the
classification, so a mocked ``db.execute`` sequence would only assert that the
implementation lines up with itself.
"""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReadingSession, Thread
from app.schemas import (
    RollBootstrapResponse,
    RollBootstrapThread,
    SessionMode,
    ThreadExclusionReason,
)
from app.schemas.session import SessionBandwidthState
from tests.conftest import get_or_create_user_async


async def _thread(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    position: int,
    status: str = "active",
    is_blocked: bool = False,
) -> Thread:
    """Persist one owned series and return it."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=position,
        status=status,
        is_blocked=is_blocked,
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _bootstrap(
    client: AsyncClient,
) -> RollBootstrapResponse:
    """Fetch the Roll bootstrap payload for the authenticated user."""
    response = await client.get("/api/v1/roll/bootstrap")
    assert response.status_code == 200
    return RollBootstrapResponse.model_validate(response.json())


def _by_id(payload: RollBootstrapResponse) -> dict[int, ThreadExclusionReason]:
    return {item.thread_id: item for item in payload.excluded_threads}


@pytest.mark.asyncio
async def test_bootstrap_explains_completed_and_active_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Every series is either available or carries a user-readable reason."""
    user = await get_or_create_user_async(async_db)
    rollable = await _thread(async_db, user.id, title="Rollable", position=1)
    blocked = await _thread(async_db, user.id, title="Blocked", position=2, is_blocked=True)
    deprioritized = await _thread(async_db, user.id, title="Deprioritized", position=0)
    completed = await _thread(
        async_db, user.id, title="Completed", position=3, status="completed"
    )
    await async_db.commit()

    payload = await _bootstrap(auth_client)

    assert payload.total_threads == 4
    assert payload.available_threads == 1
    assert payload.excluded_count == 3
    assert payload.total_threads - payload.available_threads == payload.excluded_count

    excluded = _by_id(payload)
    assert set(excluded) == {blocked.id, deprioritized.id, completed.id}
    assert excluded[blocked.id].reason == "blocked"
    assert excluded[deprioritized.id].reason == "not_in_queue"
    assert excluded[deprioritized.id].detail == "Not in the active queue"
    assert excluded[completed.id].reason == "completed"
    assert excluded[completed.id].detail == "Read the full series"

    # Only completed and deprioritized series are inactive; blocked series keep
    # their own dedicated Roll section and must not be duplicated here.
    inactive_ids = {item.thread_id for item in payload.inactive_threads}
    assert inactive_ids == {deprioritized.id, completed.id}
    assert payload.inactive_count == 2
    assert rollable.id not in excluded


@pytest.mark.asyncio
async def test_bootstrap_explains_snoozed_and_skipped_series(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Session-scoped snooze and skip both surface with distinct reasons."""
    user = await get_or_create_user_async(async_db)
    rollable = await _thread(async_db, user.id, title="Rollable", position=1)
    snoozed = await _thread(async_db, user.id, title="Snoozed", position=2)
    skipped = await _thread(async_db, user.id, title="Skipped", position=3)
    await async_db.commit()

    session = ReadingSession(
        start_die=6,
        user_id=user.id,
        snoozed_thread_ids=[snoozed.id],
        skipped_thread_ids=[skipped.id],
    )
    async_db.add(session)
    await async_db.commit()

    payload = await _bootstrap(auth_client)

    excluded = _by_id(payload)
    assert excluded[snoozed.id].reason == "snoozed"
    assert excluded[snoozed.id].detail == "Snoozed in current session"
    assert excluded[skipped.id].reason == "skipped"
    assert excluded[skipped.id].detail == "Skipped in current session"
    assert payload.available_threads == 1
    assert rollable.id not in excluded
    # Session-scope exclusions have their own Roll sections, so they are
    # excluded without being repeated as inactive.
    assert payload.inactive_count == 0


@pytest.mark.asyncio
async def test_bootstrap_exclusions_are_user_scoped(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Another user's series never appear in this user's exclusion payload."""
    owner = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="foreign_exclusion_owner")
    mine = await _thread(async_db, owner.id, title="Mine", position=1)
    theirs = await _thread(
        async_db, other.id, title="Theirs", position=1, status="completed"
    )
    await async_db.commit()

    payload = await _bootstrap(auth_client)

    excluded_ids = {item.thread_id for item in payload.excluded_threads}
    assert mine.id not in excluded_ids
    assert theirs.id not in excluded_ids
    assert payload.total_threads == 1
    assert payload.excluded_count == 0


@pytest.mark.asyncio
async def test_bootstrap_normalizes_excluded_series_format(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Excluded series report the same canonical format as pool entries."""
    user = await get_or_create_user_async(async_db)
    completed = await _thread(
        async_db, user.id, title="Completed", position=1, status="completed"
    )
    completed.format = "comics"
    await async_db.commit()

    payload = await _bootstrap(auth_client)

    [excluded] = payload.excluded_threads
    assert excluded.thread_id == completed.id
    assert excluded.format == "Comic"


def test_bootstrap_schema_bounds_excluded_lists_without_losing_counts():
    """Bounded lists keep the complete counts so the page never lies."""
    summaries = [
        RollBootstrapThread(id=index, title=f"Thread {index}", format="ongoing")
        for index in range(1, 26)
    ]

    response = RollBootstrapResponse(
        session_id=1,
        user_id=1,
        current_die=100,
        manual_die=None,
        pending_thread_id=None,
        last_rolled_result=None,
        session_mode=SessionMode(),
        active_thread=None,
        bandwidth=SessionBandwidthState(
            predicted_bandwidth=None,
            active_bandwidth=None,
            confidence=None,
            source=None,
            mode_version=None,
        ),
        roll_pool=summaries,
        snoozed_threads=summaries,
        snoozed_count=len(summaries),
        skipped_thread_ids=[],
        skipped_threads=[],
        blocked_count=len(summaries),
        blocked_threads=summaries,
        stale_thread_count=0,
        stale_thread=None,
        total_threads=len(summaries),
        available_threads=len(summaries),
        excluded_count=0,
        excluded_threads=[],
        inactive_count=0,
        inactive_threads=[],
    )

    assert len(response.excluded_threads) <= response.summary_limit
    assert len(response.inactive_threads) <= response.summary_limit
    assert response.excluded_count == 0
    assert response.inactive_count == 0