"""Roll v2 bootstrap d100 production-shape latency regression (issue #4315).

The production incident behind #4315 recorded authenticated
``GET /api/v2/roll/bootstrap`` requests at d100 that exceeded asyncpg's 8 s
``command_timeout`` on a library of ~190 threads and ~7k issues. The dominant
cost was ``fetch_series_aggregates``, which built four JSON containment
predicates per volume (about 400 ``metadata_json::jsonb @>`` clauses) and then
ran two correlated scalar subqueries per returned row.

These tests pin the replacement contract with a production-shaped dataset:

* the d100 projection finishes far below the 8 s command timeout and the 10 s
  browser abort;
* the canonical-series aggregate is exactly one statement;
* that statement uses one array predicate and no JSON containment OR fan-out;
* canonical-series stats still resolve correctly at that size.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import (
    Event,
    Issue,
    ReadingSession,
    Thread,
    User,
)
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
)
from app.services.roll_v2_projection import get_v2_rollable_projection

#: Production shape reported in #4315: ~190 active threads, ~7k issues, d100.
THREAD_COUNT = 190
ISSUES_PER_THREAD = 37
READ_ISSUES_PER_THREAD = 19
DIE_SIZE = 100

#: Hard ceiling for the projection at d100. asyncpg raises after an 8 s
#: statement timeout and the frontend aborts at 10 s, so this leaves several
#: seconds of margin while still catching an order-of-magnitude regression.
D100_PROJECTION_BUDGET_MS = 4_000.0

D1 = datetime(2026, 1, 1, tzinfo=UTC)


@dataclass
class _StatementLedger:
    """Record SELECT/CTE statements issued inside one measured block."""

    statements: list[str] = field(default_factory=list)


@contextmanager
def _measured_selects(db_engine: AsyncEngine) -> Iterator[_StatementLedger]:
    """Capture read statements executed while the context is active."""
    ledger = _StatementLedger()

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            ledger.statements.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        yield ledger
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)


def _series_metadata(volume_id: int) -> dict[str, object]:
    """Return stored catalog metadata with the provider run length."""
    return {"name": f"Series {volume_id}", "count_of_issues": ISSUES_PER_THREAD}


def _issue_metadata(volume_id: int, position: int) -> dict[str, object]:
    """Return issue metadata using both stored volume-id shapes.

    Half of the volumes use the nested ``volume.id`` shape and half use the
    flat ``volume_id`` shape, so the normalized expression is exercised on
    both production shapes at d100.
    """
    if volume_id % 2 == 0:
        return {
            "issue_number": str(position),
            "volume": {"id": volume_id, "name": f"Series {volume_id}"},
        }
    return {
        "issue_number": str(position),
        "volume_id": volume_id,
        "volume_name": f"Series {volume_id}",
    }


async def _seed_production_shape(
    db: AsyncSession, user: User, session: ReadingSession
) -> None:
    """Persist a production-shaped library for one d100 bootstrap."""
    db.add_all(
        [
            ExternalIdentity(
                provider="comicvine",
                entity_type="series",
                external_id=str(volume_id),
                metadata_json=_series_metadata(volume_id),
            )
            for volume_id in range(1, THREAD_COUNT + 1)
        ]
    )

    threads = [
        Thread(
            user_id=user.id,
            title=f"Series {volume_id}",
            format="Comic",
            issues_remaining=ISSUES_PER_THREAD - READ_ISSUES_PER_THREAD,
            total_issues=ISSUES_PER_THREAD,
            queue_position=volume_id,
            status="active",
            last_activity_at=D1,
        )
        for volume_id in range(1, THREAD_COUNT + 1)
    ]
    db.add_all(threads)
    await db.flush()

    issues_by_thread: dict[int, list[Issue]] = {}
    for thread in threads:
        assert thread.id is not None
        issues_by_thread[thread.id] = [
            Issue(
                thread_id=thread.id,
                issue_number=str(position),
                position=position,
                status="read" if position <= READ_ISSUES_PER_THREAD else "unread",
                read_at=D1 if position <= READ_ISSUES_PER_THREAD else None,
            )
            for position in range(1, ISSUES_PER_THREAD + 1)
        ]
    db.add_all([issue for issues in issues_by_thread.values() for issue in issues])
    await db.flush()

    for thread in threads:
        assert thread.id is not None
        thread.next_unread_issue_id = issues_by_thread[thread.id][READ_ISSUES_PER_THREAD].id

    identities: list[ExternalIdentity] = []
    mapping_rows: list[tuple[Issue, ExternalIdentity]] = []
    events: list[Event] = []
    for volume_id, thread in enumerate(threads, start=1):
        assert thread.id is not None
        issues = issues_by_thread[thread.id]
        # The next unread issue also keeps a confirmed identity so the
        # rollable[] row can resolve its canonical series.
        for issue in issues[: READ_ISSUES_PER_THREAD + 1]:
            identity = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id=f"{volume_id}-{issue.position}",
                metadata_json=_issue_metadata(volume_id, issue.position),
            )
            identities.append(identity)
            mapping_rows.append((issue, identity))
        for issue in issues[:READ_ISSUES_PER_THREAD]:
            events.append(
                Event(
                    type="rate",
                    thread_id=thread.id,
                    issue_id=issue.id,
                    issue_number=issue.issue_number,
                    rating=4.0,
                    timestamp=D1,
                    session_id=session.id,
                )
            )

    db.add_all(identities)
    await db.flush()
    db.add_all(
        [
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                confidence=1.0,
            )
            for issue, identity in mapping_rows
        ]
    )
    db.add_all(events)
    await db.flush()


@pytest.mark.asyncio
async def test_d100_production_shape_bootstrap_stays_under_budget(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
) -> None:
    """A ~190-thread, ~7k-issue d100 bootstrap stays far below the timeout."""
    session = ReadingSession(user_id=default_user.id, start_die=6)
    async_db.add(session)
    await async_db.flush()
    await _seed_production_shape(async_db, default_user, session)
    # Production has planner statistics; a freshly bulk-loaded test database
    # does not. Without ANALYZE, PostgreSQL falls back to default estimates and
    # can pick a nested-loop plan that neither production nor the fixed query
    # shape would produce, making the timing assertion meaningless.
    await async_db.execute(
        text(
            "ANALYZE issues, threads, external_identities, "
            "issue_external_identity_mappings, events"
        )
    )

    started_at = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        items, _last_read, omitted_thread_ids = await get_v2_rollable_projection(
            async_db,
            user_id=default_user.id,
            die_size=DIE_SIZE,
            excluded_thread_ids=[],
            session_id=session.id,
        )
    elapsed_ms = (time.perf_counter() - started_at) * 1000

    assert len(items) == DIE_SIZE
    assert omitted_thread_ids == []
    assert elapsed_ms < D100_PROJECTION_BUDGET_MS, (
        f"d100 projection took {elapsed_ms:.0f} ms, "
        f"budget is {D100_PROJECTION_BUDGET_MS:.0f} ms"
    )

    # Canonical-series stats still resolve for every d100 row, across both
    # stored volume-id shapes.
    assert {item.identity.canonical_series_id for item in items} == {
        str(volume_id) for volume_id in range(1, DIE_SIZE + 1)
    }
    assert {item.reader.read_count for item in items} == {READ_ISSUES_PER_THREAD}
    assert {item.reader.issue_count for item in items} == {ISSUES_PER_THREAD}
    assert {item.reader.rating_count for item in items} == {READ_ISSUES_PER_THREAD}
    first = items[0]
    assert first.reader.latest_rating == pytest.approx(4.0)

    # The aggregate is one statement with a single array predicate. The old
    # implementation emitted ~400 jsonb containment clauses for this input.
    # JSON metadata keys are bound parameters, so the normalized volume
    # expression is the stable statement marker.
    series_statements = [
        statement for statement in ledger.statements if "regexp_replace" in statement
    ]
    assert len(series_statements) == 1, (
        f"series aggregate issued {len(series_statements)} statements; "
        "expected exactly one"
    )
    series_statement = series_statements[0]
    assert "= ANY" in series_statement
    assert "@>" not in series_statement
    assert all("@>" not in statement for statement in ledger.statements)
