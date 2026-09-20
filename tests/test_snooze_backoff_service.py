"""Focused tests for cross-session snooze backoff derivation.

Issue #2740: Snooze is a durable session-based eligibility backoff derived
from stored events and session history, not current-session state alone.
These tests drive ``derive_cross_session_excluded_thread_ids`` with mocked
repository rows so the eligibility policy is exercised without a database.

Behavior fixed here matches the issue contract:

- a backoff of ``N`` makes a thread eligible once ``N`` later reading
  sessions have started after the latest snooze;
- successful reads reset the streak via ``Thread.last_activity_at``;
- a newer manual ``unsnooze`` makes the thread eligible immediately while
  preserving the streak for the next snooze;
- elapsed real time away from ComicPile does not burn down a snooze;
- each thread is evaluated independently.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.services.snooze_service import derive_cross_session_excluded_thread_ids

BASE = datetime(2026, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def _row(
    thread_id: int,
    last_activity: datetime | None,
    event_type: str | None,
    timestamp: datetime | None,
    event_id: int,
) -> tuple[int, datetime | None, str | None, datetime | None, int]:
    """Build a snooze-backoff evidence row as returned by the repository."""
    return (thread_id, last_activity, event_type, timestamp, event_id)


async def _derive(
    rows: list[tuple[int, datetime | None, str | None, datetime | None, int]],
    session_starts: list[datetime],
) -> set[int]:
    """Run the derivation with the supplied evidence, mocking the repository."""
    db = AsyncMock()
    with (
        patch(
            "app.services.snooze_service.fetch_snooze_backoff_rows",
            AsyncMock(return_value=rows),
        ),
        patch(
            "app.services.snooze_service.fetch_user_session_started_ats",
            AsyncMock(return_value=session_starts),
        ),
    ):
        return await derive_cross_session_excluded_thread_ids(db, 7)


@pytest.mark.asyncio
async def test_no_snooze_evidence_yields_no_exclusions() -> None:
    """A user with no snooze evidence has no cross-session exclusions."""
    db = AsyncMock()
    with patch(
        "app.services.snooze_service.fetch_snooze_backoff_rows",
        AsyncMock(return_value=[]),
    ) as rows:
        excluded = await derive_cross_session_excluded_thread_ids(db, 7)
    assert excluded == set()
    rows.assert_awaited_once_with(db, 7)


@pytest.mark.asyncio
async def test_first_snooze_requires_one_later_session() -> None:
    """Snooze #1 needs one later reading session before becoming eligible."""
    rows = [_row(1, None, "snooze", BASE, 10)]
    assert await _derive(rows, [BASE]) == {1}
    assert await _derive(rows, [BASE + HOUR]) == set()


@pytest.mark.asyncio
async def test_third_snooze_requires_two_later_sessions() -> None:
    """Snooze #3 requires two later sessions, matching 1,1,2,2,... sequence."""
    rows = [_row(1, None, "snooze", BASE + i * HOUR, 10 + i) for i in range(3)]
    latest = BASE + 2 * HOUR
    assert await _derive(rows, [latest + HOUR]) == {1}
    assert await _derive(rows, [latest + HOUR, latest + 2 * HOUR]) == set()


@pytest.mark.asyncio
async def test_read_resets_the_streak() -> None:
    """Snoozes before the last successful read do not count toward the streak."""
    read_at = BASE + 5 * HOUR
    rows = [
        _row(1, read_at, "snooze", BASE + HOUR, 10),
        _row(1, read_at, "snooze", BASE + 2 * HOUR, 11),
        _row(1, read_at, "snooze", read_at + HOUR, 12),
    ]
    assert await _derive(rows, [read_at]) == {1}
    assert await _derive(rows, [read_at + 2 * HOUR]) == set()


@pytest.mark.asyncio
async def test_unsnooze_after_latest_snooze_makes_thread_eligible() -> None:
    """A newer manual unsnooze wins immediately, regardless of session count."""
    rows = [
        _row(1, None, "snooze", BASE, 10),
        _row(1, None, "unsnooze", BASE + HOUR, 11),
    ]
    assert await _derive(rows, [BASE]) == set()


@pytest.mark.asyncio
async def test_unsnooze_preserves_streak_for_next_snooze() -> None:
    """Unsnooze does not reset the streak; the next snooze continues it."""
    rows = [
        _row(1, None, "snooze", BASE, 10),
        _row(1, None, "snooze", BASE + HOUR, 11),
        _row(1, None, "unsnooze", BASE + 2 * HOUR, 12),
        _row(1, None, "snooze", BASE + 3 * HOUR, 13),
    ]
    latest = BASE + 3 * HOUR
    assert await _derive(rows, [latest + HOUR]) == {1}
    assert await _derive(rows, [latest + HOUR, latest + 2 * HOUR]) == set()


@pytest.mark.asyncio
async def test_elapsed_time_away_does_not_advance_snooze() -> None:
    """Long real-time gaps without new sessions do not burn down a snooze."""
    rows = [_row(1, None, "snooze", BASE, 10)]
    weeks_later = BASE + 30 * timedelta(days=1)
    assert await _derive(rows, [BASE]) == {1}
    assert await _derive(rows, [BASE, weeks_later]) == set()


@pytest.mark.asyncio
async def test_session_started_exactly_at_snooze_does_not_count() -> None:
    """A session that started at the same instant as the snooze is not later."""
    rows = [_row(1, None, "snooze", BASE, 10)]
    assert await _derive(rows, [BASE]) == {1}
    assert await _derive(rows, [BASE + timedelta(seconds=1)]) == set()


@pytest.mark.asyncio
async def test_threads_without_streaks_are_never_excluded() -> None:
    """Threads without snoozes after the reset boundary stay eligible."""
    rows = [
        _row(1, None, None, None, 0),
        _row(2, BASE, "snooze", BASE, 10),
    ]
    assert await _derive(rows, [BASE]) == set()


@pytest.mark.asyncio
async def test_threads_are_evaluated_independently() -> None:
    """One thread under backoff does not pull unrelated threads out."""
    rows = [
        _row(1, None, "snooze", BASE, 10),
        _row(2, None, "snooze", BASE + HOUR, 11),
        _row(3, None, "snooze", BASE, 12),
        _row(3, None, "snooze", BASE + HOUR, 13),
        _row(3, None, "snooze", BASE + 2 * HOUR, 14),
    ]
    session_starts = [BASE + 3 * HOUR]
    excluded = await _derive(rows, session_starts)
    assert excluded == {3}
    assert 1 not in excluded
    assert 2 not in excluded


@pytest.mark.asyncio
async def test_derivation_is_batched_regardless_of_candidate_count() -> None:
    """A fixed pair of repository queries serves any number of threads."""
    thread_count = 200
    rows = [
        row
        for thread_id in range(1, thread_count + 1)
        for row in (
            _row(thread_id, None, "snooze", BASE + thread_id * HOUR, thread_id),
            _row(
                thread_id,
                None,
                "snooze",
                BASE + (thread_id + thread_count) * HOUR,
                thread_id + 1000,
            ),
        )
    ]
    sessions = [BASE + (2 * thread_count + 1) * HOUR]
    db = AsyncMock()
    with (
        patch(
            "app.services.snooze_service.fetch_snooze_backoff_rows",
            AsyncMock(return_value=rows),
        ) as rows_patch,
        patch(
            "app.services.snooze_service.fetch_user_session_started_ats",
            AsyncMock(return_value=sessions),
        ) as sessions_patch,
    ):
        await derive_cross_session_excluded_thread_ids(db, 7)
    rows_patch.assert_awaited_once_with(db, 7)
    sessions_patch.assert_awaited_once_with(db, 7)
