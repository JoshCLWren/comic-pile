"""Roll-pool exclusion explanations (issue #3125).

The roll bootstrap deliberately keeps series out of the roll pool. Every one of
those exclusions has to reach the Roll page with a named reason, otherwise a
series silently vanishes from every roll and the reader has no way to tell
whether it is blocked, snoozed, skipped, or simply behind the die.

These tests cover the two exclusions that previously had no payload at all:
durable cross-session snooze backoff (#2740) and the die boundary.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession as SQLAlchemyAsyncSession

from app.api import roll as roll_api
from app.models import Thread
from app.repositories.roll_repository import (
    count_backoff_snoozed_threads,
    count_roll_pool_overflow,
    fetch_backoff_snoozed_threads,
)
from tests.conftest import get_or_create_user_async


class _Result:
    """Minimal SQLAlchemy result double for the bootstrap query sequence."""

    def __init__(self, *, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar_value

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self


def _mode_session(**kwargs):
    """Build a session double carrying every bootstrap-exposed mode attribute."""
    mode_fields = {
        "manual_die": None,
        "pending_thread_id": None,
        "snoozed_thread_ids": [],
        "skipped_thread_ids": [],
        "active_bandwidth": None,
        "predicted_bandwidth": None,
        "bandwidth_confidence": None,
        "bandwidth_source": None,
        "bandwidth_version": None,
        "active_intent": None,
        "predicted_intent": None,
        "intent_confidence": None,
        "intent_source": None,
        "intent_version": None,
        "session_mode_correction_guidance": None,
    }
    return SimpleNamespace(**{**mode_fields, **kwargs})


async def _add_thread(
    db: SQLAlchemyAsyncSession,
    *,
    user_id: int,
    title: str,
    position: int,
    is_blocked: bool = False,
    status: str = "active",
) -> Thread:
    """Insert one owned thread and return it after flush."""
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


@pytest.mark.asyncio
async def test_backoff_snoozed_series_are_resolved_and_counted(
    async_db: SQLAlchemyAsyncSession,
) -> None:
    """Durable snooze backoff must name the active series it holds out."""
    user = await get_or_create_user_async(async_db)
    other = await get_or_create_user_async(async_db, username="backoff_foreign_owner")

    eligible = await _add_thread(async_db, user_id=user.id, title="Saga", position=1)
    completed = await _add_thread(
        async_db, user_id=user.id, title="Finished", position=2, status="completed"
    )
    await _add_thread(async_db, user_id=user.id, title="Foreign", position=3)
    foreign = await _add_thread(async_db, user_id=other.id, title="Other Owner", position=1)
    await async_db.commit()

    backoff_ids = [eligible.id, completed.id, foreign.id]

    assert await count_backoff_snoozed_threads(async_db, user.id, backoff_ids) == 1
    assert await fetch_backoff_snoozed_threads(async_db, user.id, backoff_ids, 20) == [
        (eligible.id, "Saga", "Comic")
    ]


@pytest.mark.asyncio
async def test_backoff_queries_short_circuit_without_ids(
    async_db: SQLAlchemyAsyncSession,
) -> None:
    """An empty backoff set must not cost a query or return rows."""
    assert await count_backoff_snoozed_threads(async_db, 1, []) == 0
    assert await fetch_backoff_snoozed_threads(async_db, 1, [], 20) == []


@pytest.mark.asyncio
async def test_backoff_snoozed_list_respects_the_summary_limit(
    async_db: SQLAlchemyAsyncSession,
) -> None:
    """The bounded summary list must not exceed the caller's limit."""
    user = await get_or_create_user_async(async_db)
    threads = [
        await _add_thread(async_db, user_id=user.id, title=f"Series {index}", position=index)
        for index in range(1, 4)
    ]
    await async_db.commit()

    backoff_ids = [thread.id for thread in threads]

    assert await count_backoff_snoozed_threads(async_db, user.id, backoff_ids) == 3
    limited = await fetch_backoff_snoozed_threads(async_db, user.id, backoff_ids, 2)
    assert [row[0] for row in limited] == [threads[0].id, threads[1].id]


@pytest.mark.asyncio
async def test_die_boundary_overflow_counts_only_eligible_series(
    async_db: SQLAlchemyAsyncSession,
) -> None:
    """Only series the die alone excludes count as overflow."""
    user = await get_or_create_user_async(async_db)

    eligible = [
        await _add_thread(async_db, user_id=user.id, title=f"Eligible {index}", position=index)
        for index in range(1, 6)
    ]
    blocked = await _add_thread(
        async_db, user_id=user.id, title="Blocked", position=6, is_blocked=True
    )
    snoozed = await _add_thread(async_db, user_id=user.id, title="Snoozed", position=7)
    skipped = await _add_thread(async_db, user_id=user.id, title="Skipped", position=8)
    await _add_thread(async_db, user_id=user.id, title="Off Queue", position=0)
    await async_db.commit()

    # Five eligible series, three of which fit on a d3 die.
    assert (
        await count_roll_pool_overflow(async_db, user.id, 3, [snoozed.id], [skipped.id]) == 2
    )
    # A die at least as large as the queue hides nothing.
    assert (
        await count_roll_pool_overflow(async_db, user.id, len(eligible), [snoozed.id], [skipped.id])
        == 0
    )
    assert await count_roll_pool_overflow(async_db, user.id, 50) == 0
    assert blocked.id not in eligible


@pytest.mark.asyncio
async def test_die_boundary_overflow_matches_pool_filters(
    async_db: SQLAlchemyAsyncSession,
) -> None:
    """Overflow must apply the same snooze/skip filters as the pool query."""
    user = await get_or_create_user_async(async_db)

    for index in range(1, 4):
        await _add_thread(async_db, user_id=user.id, title=f"Eligible {index}", position=index)
    snoozed = await _add_thread(async_db, user_id=user.id, title="Snoozed", position=4)
    skipped = await _add_thread(async_db, user_id=user.id, title="Skipped", position=5)
    await async_db.commit()

    # Three eligible series minus the die boundary is zero.
    assert await count_roll_pool_overflow(async_db, user.id, 3) == 0
    # Removing the snoozed and skipped series cannot change the eligible count.
    assert (
        await count_roll_pool_overflow(async_db, user.id, 3, [snoozed.id, skipped.id]) == 0
    )


@pytest.mark.asyncio
async def test_bootstrap_reports_backoff_and_overflow_exclusions(monkeypatch) -> None:
    """Bootstrap must expose both previously invisible exclusions."""
    current_session = _mode_session(id=55, timezone=None)
    current_user = SimpleNamespace(id=7)
    backoff_thread = (9, "Saga", "ongoing")

    monkeypatch.setattr(
        roll_api, "get_or_create", AsyncMock(return_value=current_session)
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(
        roll_api, "get_current_die_for_session", AsyncMock(return_value=4)
    )
    monkeypatch.setattr(
        roll_api,
        "derive_cross_session_excluded_thread_ids",
        AsyncMock(return_value={9}),
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=1),
        _Result(rows=[SimpleNamespace(id=9, title="Saga", format="ongoing")]),
        _Result(scalar_value=11),
        _Result(scalar_value=0),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    assert response.snoozed_backoff_count == 1
    assert [(thread.id, thread.title) for thread in response.snoozed_backoff_threads] == [
        (backoff_thread[0], backoff_thread[1])
    ]
    # Eleven eligible series on a d4 die leaves seven beyond the boundary.
    assert response.pool_overflow_count == 7


@pytest.mark.asyncio
async def test_bootstrap_excludes_session_snoozed_from_backoff_list(monkeypatch) -> None:
    """A series snoozed this session is reported once, under the session list."""
    current_session = _mode_session(id=55, snoozed_thread_ids=[9], timezone=None)
    current_user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        roll_api, "get_or_create", AsyncMock(return_value=current_session)
    )
    monkeypatch.setattr(
        roll_api,
        "get_session_with_thread_safe",
        AsyncMock(return_value=(current_session, None)),
    )
    monkeypatch.setattr(
        roll_api, "get_current_die_for_session", AsyncMock(return_value=4)
    )
    monkeypatch.setattr(
        roll_api,
        "derive_cross_session_excluded_thread_ids",
        AsyncMock(return_value={9}),
    )

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(rows=[]),
        _Result(rows=[SimpleNamespace(id=9, title="Saga", format="ongoing")]),
        _Result(scalar_value=0),
        _Result(rows=[]),
        _Result(scalar_value=0),
        _Result(scalar_value=0),
    ]

    response = await roll_api.roll_bootstrap(current_user=current_user, db=db)

    assert response.snoozed_count == 1
    assert response.snoozed_backoff_count == 0
    assert response.snoozed_backoff_threads == []