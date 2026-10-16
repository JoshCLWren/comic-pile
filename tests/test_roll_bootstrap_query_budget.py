"""Roll bootstrap SELECT budget (issue #3375).

The production incident behind #3375 recorded ``GET /api/v1/roll/bootstrap``
at 1962 ms against a 1000 ms budget with 36 database queries and 1326 ms of
database time. The endpoint fans out across the ``threads`` table for the roll
pool, the snoozed and skipped summaries, the blocked summary plus its count,
the stale summary plus its candidate set plus its chosen row, and the full
active and completed library used for exclusion transparency.

Each of those round trips is independent, so the fix is to answer them with a
bounded set of queries instead of one query per question. These tests pin the
budget so a future change cannot quietly reintroduce per-thread or per-section
fan-out.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import ReadingSession, Thread
from tests.conftest import get_or_create_user_async

#: Maximum number of ``SELECT`` statements a single bootstrap request may
#: issue for a fully populated library (pool, snoozed, skipped, blocked,
#: stale, completed, and deprioritized series all present). Every section of
#: the response is answered by one batched query, so the ceiling holds as the
#: library grows. Before issue #3375 the same request issued 20 statements.
BOOTSTRAP_SELECT_BUDGET = 15

#: Days of inactivity after which an unblocked active series counts as stale.
STALE_AFTER_DAYS = 7


async def _add_series(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    position: int,
    status: str = "active",
    is_blocked: bool = False,
    last_activity_at: datetime | None = None,
) -> Thread:
    """Persist one owned series for the bootstrap library."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="Comic",
        issues_remaining=3,
        queue_position=position,
        status=status,
        is_blocked=is_blocked,
        last_activity_at=last_activity_at,
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _capture_selects(
    client: AsyncClient,
    db_engine: AsyncEngine,
) -> list[str]:
    """Return every ``SELECT`` statement issued by one bootstrap request."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        response = await client.get("/api/v1/roll/bootstrap")
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)
    assert response.status_code == 200
    return statements


async def _populate_library(
    db: AsyncSession,
    user_id: int,
    *,
    rollable_count: int,
) -> None:
    """Create every bootstrap section for the user in one transaction."""
    position = 0
    for index in range(1, rollable_count + 1):
        position += 1
        await _add_series(
            db, user_id, title=f"Rollable {index}", position=position
        )

    snoozed = await _add_series(db, user_id, title="Snoozed", position=position + 1)
    skipped = await _add_series(db, user_id, title="Skipped", position=position + 2)
    await _add_series(
        db, user_id, title="Blocked", position=position + 3, is_blocked=True
    )
    stale = await _add_series(
        db,
        user_id,
        title="Stale",
        position=position + 4,
        last_activity_at=datetime.now(UTC) - timedelta(days=STALE_AFTER_DAYS + 3),
    )
    await _add_series(db, user_id, title="Deprioritized", position=0)
    await _add_series(
        db, user_id, title="Completed", position=position + 5, status="completed"
    )
    await db.flush()

    session = ReadingSession(
        start_die=6,
        user_id=user_id,
        snoozed_thread_ids=[snoozed.id],
        skipped_thread_ids=[skipped.id],
    )
    db.add(session)
    await db.commit()

    assert stale.id is not None


@pytest.mark.asyncio
async def test_bootstrap_select_count_stays_within_budget(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """A fully populated library answers every section within the budget."""
    user = await get_or_create_user_async(async_db)
    await _populate_library(async_db, user.id, rollable_count=8)

    statements = await _capture_selects(auth_client, db_engine)

    assert len(statements) <= BOOTSTRAP_SELECT_BUDGET, (
        f"bootstrap issued {len(statements)} SELECT statements, "
        f"budget is {BOOTSTRAP_SELECT_BUDGET}"
    )


@pytest.mark.asyncio
async def test_bootstrap_select_count_is_constant_as_the_pool_grows(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Growing the rollable library must not add round trips."""
    user = await get_or_create_user_async(async_db)
    await _populate_library(async_db, user.id, rollable_count=2)
    small_pool = await _capture_selects(auth_client, db_engine)

    await _populate_library(async_db, user.id, rollable_count=12)
    large_pool = await _capture_selects(auth_client, db_engine)

    assert len(large_pool) == len(small_pool)