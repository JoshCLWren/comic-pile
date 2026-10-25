"""Route-level SQL budget regression for ``POST /api/v1/roll/`` (issue #1255).

The production HAR behind the reopened issue recorded 84 database queries for
one successful roll because ``RollService.select_pending_thread`` and the
light/deep bandwidth path each resolved reading effort once per die candidate.
This regression pins the whole request, including authentication and response
assembly, to a hard statement budget and proves the count does not grow with
the bounded die pool.

The test drives the real HTTP route against the database-backed test engine and
counts every statement through SQLAlchemy's ``before_cursor_execute`` hook. It
intentionally does not mock service calls: a future per-candidate query loop
must show up as extra statements here.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Event, ExternalIdentity, Issue, ReadingSession, Thread, User
from app.models.external_identity import ThreadExternalSeriesMapping

#: Hard ceiling for one representative successful roll, including auth,
#: selection, recommendation persistence, and response assembly. The issue's
#: acceptance target is 25 total statements with no candidate-count growth.
ROLL_STATEMENT_BUDGET = 25

#: Die sizes exercised by the acceptance contract.
DIE_SIZES = (6, 20, 100)

#: Bandwidth/intent combinations that decide which selection paths run.
ROLL_MODES: dict[str, dict[str, str]] = {
    "balanced": {"bandwidth": "balanced", "intent": "balanced"},
    "light": {"bandwidth": "light", "intent": "balanced"},
    "deep": {"bandwidth": "deep", "intent": "balanced"},
    "random": {"bandwidth": "light", "intent": "random"},
}

#: Size of the populated library. It exceeds the largest die so the d100 case
#: has a genuine 100-candidate bounded pool.
LIBRARY_SIZE = 100


async def _add_thread(
    db: AsyncSession,
    user_id: int,
    *,
    title: str,
    queue_position: int,
) -> Thread:
    """Create one active thread for the reader's roll pool."""
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=5,
        total_issues=5,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        created_at=datetime.now(UTC) - timedelta(days=30),
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    await db.flush()
    return thread


async def _confirm_series_era(
    db: AsyncSession,
    thread: Thread,
    *,
    cover_date: str,
) -> None:
    """Attach confirmed series metadata so the effort batch reads it."""
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=f"4050-{thread.id}",
        metadata_json={"cover_date": cover_date},
    )
    db.add(identity)
    await db.flush()
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )
    await db.flush()


async def _add_observed_effort(
    db: AsyncSession,
    thread: Thread,
    *,
    minutes: float,
    count: int,
) -> None:
    """Seed linked roll-to-rate observations for a populated-history case."""
    base = datetime.now(UTC) - timedelta(days=10)
    for index in range(count):
        rolled_at = base + timedelta(days=index)
        roll_event = Event(
            type="roll",
            selected_thread_id=thread.id,
            die=6,
            result=1,
            selection_method="random",
            timestamp=rolled_at,
        )
        db.add(roll_event)
        await db.flush()
        db.add(
            Event(
                type="rate",
                thread_id=thread.id,
                source_roll_event_id=roll_event.id,
                rating=4.0,
                issues_read=1,
                die=6,
                die_after=8,
                timestamp=rolled_at + timedelta(minutes=minutes),
            )
        )
        await db.flush()


async def _seed_library(
    db: AsyncSession,
    user: User,
    *,
    size: int,
) -> ReadingSession:
    """Populate the reader's queue, history, and active session."""
    threads: list[Thread] = []
    for index in range(size):
        thread = await _add_thread(
            db,
            user.id,
            title=f"Series {index + 1}",
            queue_position=index + 1,
        )
        # Alternate era buckets so the batched publication-year read has real
        # work to do for every candidate.
        await _confirm_series_era(
            db,
            thread,
            cover_date="1965-01-01" if index % 3 == 0 else "2015-01-01",
        )
        threads.append(thread)

    for thread, minutes in zip(threads[:3], (5.0, 20.0, 45.0), strict=False):
        await _add_observed_effort(db, thread, minutes=minutes, count=3)

    reading_session = ReadingSession(
        start_die=6,
        manual_die=6,
        user_id=user.id,
        active_bandwidth="balanced",
        active_intent="balanced",
        bandwidth_source="manual",
        intent_source="manual",
    )
    db.add(reading_session)
    await db.commit()
    return reading_session


async def _capture_roll_statements(
    client: AsyncClient,
    db_engine: AsyncEngine,
    *,
    bandwidth: str,
    intent: str,
) -> list[str]:
    """Return every SQL statement issued by one successful roll request."""
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        response = await client.post(
            "/api/v1/roll/",
            json={"bandwidth": bandwidth, "intent": intent},
        )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)
    assert response.status_code == 200, response.text
    return statements


async def _dismiss_pending(client: AsyncClient) -> None:
    """Clear the pending roll between captured requests."""
    response = await client.post("/api/v1/roll/dismiss-pending")
    assert response.status_code == 204, response.text


@pytest.mark.asyncio
async def test_roll_statement_count_is_bounded_and_pool_independent(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """d6/d20/d100 stay under budget for every selection mode."""
    reading_session = await _seed_library(async_db, default_user, size=LIBRARY_SIZE)

    counts: dict[str, dict[int, int]] = {mode: {} for mode in ROLL_MODES}
    for die in DIE_SIZES:
        reading_session.manual_die = die
        reading_session.start_die = die
        await async_db.commit()

        for mode, selection in ROLL_MODES.items():
            statements = await _capture_roll_statements(
                auth_client,
                db_engine,
                bandwidth=selection["bandwidth"],
                intent=selection["intent"],
            )
            counts[mode][die] = len(statements)
            assert len(statements) <= ROLL_STATEMENT_BUDGET, (
                f"{mode} roll at d{die} issued {len(statements)} statements, "
                f"budget is {ROLL_STATEMENT_BUDGET}"
            )
            await _dismiss_pending(auth_client)

    for mode, per_die in counts.items():
        assert len(set(per_die.values())) == 1, (
            f"{mode} roll statement count grew with the die pool: {per_die}"
        )


@pytest.mark.asyncio
async def test_forced_legacy_roll_stays_within_budget(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator legacy kill switch keeps the same bounded request cost."""
    await _seed_library(async_db, default_user, size=6)

    from app.config import get_recommendation_settings

    monkeypatch.setenv("RECOMMENDATION_CONTROL_MODE", "legacy")
    get_recommendation_settings.cache_clear()
    try:
        statements = await _capture_roll_statements(
            auth_client,
            db_engine,
            bandwidth="balanced",
            intent="balanced",
        )
    finally:
        monkeypatch.delenv("RECOMMENDATION_CONTROL_MODE", raising=False)
        get_recommendation_settings.cache_clear()

    assert len(statements) <= ROLL_STATEMENT_BUDGET, (
        f"forced-legacy roll issued {len(statements)} statements, "
        f"budget is {ROLL_STATEMENT_BUDGET}"
    )


@pytest.mark.asyncio
async def test_batch_effort_matches_reference_with_constant_reads(
    async_db: AsyncSession, db_engine: AsyncEngine, default_user: User,
) -> None:
    """Bulk effort preserves scalar precedence with at most three read queries."""
    from sqlalchemy import select
    from app.services.reading_effort import (
        aggregate_observations, collect_classified_observations,
        compute_effort_estimates_batch, era_prior_minutes,
        resolve_effort_estimate, resolve_publication_year,
    )

    await _seed_library(async_db, default_user, size=LIBRARY_SIZE)
    threads = list((await async_db.scalars(
        select(Thread).where(Thread.user_id == default_user.id).order_by(Thread.id)
    )).all())
    candidates = [(thread.id, thread.next_unread_issue_id) for thread in threads]
    # Include issue-less legacy and missing candidates without losing order.
    candidates.extend([(threads[0].id, None), (threads[-1].id, None)])
    observations = await collect_classified_observations(async_db, default_user.id)
    by_issue, by_thread = aggregate_observations(observations)
    reference = {}
    for thread_id, issue_id in candidates:
        year = await resolve_publication_year(async_db, thread_id=thread_id, issue_id=issue_id)
        reference[(thread_id, issue_id)] = resolve_effort_estimate(
            by_issue.get((thread_id, issue_id)) if issue_id is not None else None,
            by_thread.get(thread_id), era_prior_minutes(year),
        )
    statements: list[str] = []

    def capture(_conn: object, _cursor: object, statement: str,
                _parameters: object, _context: object, _executemany: bool) -> None:
        statements.append(statement)

    for size in (1, 6, 20, 100, len(candidates)):
        statements.clear()
        selected = candidates[:size] + candidates[:1]
        event.listen(db_engine.sync_engine, "before_cursor_execute", capture)
        try:
            result = await compute_effort_estimates_batch(
                async_db, user_id=default_user.id, candidates=selected,
            )
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", capture)
        assert len(statements) <= 3
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
        assert list(result) == list(dict.fromkeys(selected))
        assert result == {key: reference[key] for key in selected}
