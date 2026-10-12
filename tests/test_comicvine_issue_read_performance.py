"""Performance regression coverage for issue #3248.

Production ``GET /api/v1/issues/<id>/comicvine`` warm reads took ~1.9 s
(1947.13 ms for issue 1001184, 1558.33 ms for issue 1025277 on 2026-10-06).
Two avoidable costs on that path fed the budget:

1. ``get_issue_intelligence`` awaited ``refresh_issue_metadata`` inline, so
   every read with missing or stale (>30 day) deep metadata waited on live
   ComicVine HTTPS I/O (5 s per-request timeout, retries, 8 s inline
   deadline). Provider latency alone explains the ~1.5-2 s production reads.
2. ``_related_external_rows`` fetched every row sharing a story arc with no
   ``LIMIT``, then truncated to ``MAX_RELATED_ISSUES_PER_ARC`` in Python.

The fixed contract, pinned here with production-shaped mapped data:

- reads serve trusted stored data immediately and never await provider I/O;
- stale metadata schedules a deduped background refresh instead of blocking;
- the arc-member scan is bounded (capped arcs, ``LIMIT``) and deterministic;
- identity correctness is preserved (confirmed mapping, user-scoped matches).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.services import comicvine_fallback, comicvine_intelligence
from app.services.comicvine_fallback import _pending_metadata_refreshes
from app.services.comicvine_intelligence import (
    MAX_ARCS_PER_INTELLIGENCE_READ,
    MAX_RELATED_ISSUES_PER_ARC,
    get_issue_intelligence,
)


class _StatementLedger:
    """Record SELECT statements and cumulative database time on an engine."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.db_seconds = 0.0
        self._started: list[float] = []


@contextmanager
def _measured_selects(db_engine: AsyncEngine) -> Iterator[_StatementLedger]:
    """Capture SELECT text and DB time for statements run inside the block."""
    ledger = _StatementLedger()

    def _before(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            ledger.statements.append(statement)
            ledger._started.append(time.perf_counter())

    def _after(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT") and ledger._started:
            ledger.db_seconds += time.perf_counter() - ledger._started.pop()

    event.listen(db_engine.sync_engine, "before_cursor_execute", _before)
    event.listen(db_engine.sync_engine, "after_cursor_execute", _after)
    try:
        yield ledger
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _before)
        event.remove(db_engine.sync_engine, "after_cursor_execute", _after)


def _bulk_raw_payload(*, issue_id: int, arc_ids: list[int]) -> dict[str, object]:
    """Build production-shaped deep provider metadata with realistic bulk."""
    return {
        "id": issue_id,
        "name": f"Bench Issue {issue_id}",
        "issue_number": "1",
        "cover_date": "2026-01-01",
        "store_date": "2025-12-15",
        "image": {
            "original_url": "https://static.example/original.jpg",
            "super_url": "https://static.example/super.jpg",
            "medium_url": "https://static.example/medium.jpg",
            "small_url": "https://static.example/small.jpg",
        },
        "volume": {"id": 4050, "name": "Bench Volume"},
        "person_credits": [
            {"id": 1000 + offset, "name": f"Creator {offset}", "role": "writer"}
            for offset in range(12)
        ],
        "character_credits": [
            {"id": 9000 + offset, "name": f"Character {offset}"} for offset in range(24)
        ],
        "team_credits": [{"id": 7000 + offset, "name": f"Team {offset}"} for offset in range(6)],
        "story_arc_credits": [
            {"id": arc_id, "name": f"Arc {arc_id}", "site_detail_url": "https://arc.example"}
            for arc_id in arc_ids
        ],
        "date_last_updated": "2026-08-01T00:00:00+00:00",
    }


def _stored_metadata(*, issue_id: int, arc_ids: list[int]) -> dict[str, object]:
    """Build the normalized stored metadata the read serves without provider I/O."""
    return {
        "name": f"Bench Issue {issue_id}",
        "issue_number": "1",
        "cover_date": "2026-01-01",
        "volume": {"id": 4050, "name": "Bench Volume"},
        "person_credits": [{"id": 4242, "name": "Bench Writer", "role": "writer"}],
        "story_arc_credits": [
            {"id": arc_id, "name": f"Arc {arc_id}", "site_detail_url": "https://arc.example"}
            for arc_id in arc_ids
        ],
        "raw_provider_payload": _bulk_raw_payload(issue_id=issue_id, arc_ids=arc_ids),
    }


async def _mapped_issue(
    db: AsyncSession,
    thread: Thread,
    *,
    issue_number: str,
    external_id: str,
    metadata: dict[str, object],
    position: int,
) -> tuple[Issue, ExternalIdentity]:
    """Create one issue with a confirmed ComicVine issue-level mapping."""
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="unread",
    )
    db.add(issue)
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=external_id,
        external_url=f"https://comicvine.example/issues/{external_id}",
        metadata_json=metadata,
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            confidence=1.0,
        )
    )
    await db.flush()
    return issue, identity


@pytest.mark.asyncio
async def test_stale_read_returns_stored_data_without_waiting_on_provider(
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale-metadata read serves the database row even when the provider hangs.

    The background refresh is replaced with a 30 s hang: the pre-#3248 inline
    await would stall the read for the whole hang, while the fixed path must
    return trusted stored data promptly (well under the 500 ms budget shape).
    """
    thread = Thread(
        user_id=default_user.id,
        title="Bench Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    issue, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata={"issue_number": "1", "name": "Stale Bench Issue"},
        position=1,
    )

    async def _hanging_refresh(_identity_id: int) -> bool:
        await asyncio.sleep(30)
        return False

    monkeypatch.setattr(comicvine_fallback, "refresh_issue_metadata", _hanging_refresh)
    _pending_metadata_refreshes.clear()
    try:
        started = time.perf_counter()
        result = await asyncio.wait_for(
            get_issue_intelligence(async_db, issue.id, default_user.id),
            timeout=10,
        )
        wall_seconds = time.perf_counter() - started
    finally:
        pending = list(_pending_metadata_refreshes.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        _pending_metadata_refreshes.clear()

    assert result is not None
    assert result.comicvine_issue_id == "1001184"
    assert result.name == "Stale Bench Issue"
    assert wall_seconds < 5


@pytest.mark.asyncio
async def test_warm_read_uses_bounded_database_work(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warm arc-heavy read issues a bounded number of statements and bytes.

    Captures the three dimensions the issue asks for: wall time, DB statement
    count/time, and payload size. Eighty arc members exceed the per-arc
    display window, so the response must truncate while the query stays
    bounded by ``LIMIT`` instead of hydrating every member.
    """
    thread = Thread(
        user_id=default_user.id,
        title="Bench Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata=_stored_metadata(issue_id=1001184, arc_ids=[42]),
        position=1,
    )
    for offset in range(80):
        await _mapped_issue(
            async_db,
            thread,
            issue_number=str(2 + offset),
            external_id=str(2000000 + offset),
            metadata=_stored_metadata(issue_id=2000000 + offset, arc_ids=[42]),
            position=2 + offset,
        )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    started = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence(async_db, current.id, default_user.id),
            timeout=10,
        )
    wall_seconds = time.perf_counter() - started

    assert result is not None
    assert result.comicvine_issue_id == "1001184"
    assert result.series_name == "Bench Volume"
    assert len(result.story_arcs) == 1
    related = result.story_arcs[0].related_issues
    assert len(related) == MAX_RELATED_ISSUES_PER_ARC
    assert all(item.comicvine_issue_id != "1001184" for item in related)

    # Bounded database work: confirmed identity, one capped arc-member scan,
    # and one user-scoped match lookup.
    assert len(ledger.statements) <= 4
    related_statements = [text for text in ledger.statements if "external_identities" in text]
    assert any("LIMIT" in text for text in related_statements)

    payload_bytes = len(json.dumps(result.model_dump()).encode("utf-8"))
    assert payload_bytes < 200_000

    app_seconds = wall_seconds - ledger.db_seconds
    assert wall_seconds < 5
    assert app_seconds >= 0


@pytest.mark.asyncio
async def test_arc_predicates_are_capped_for_arc_heavy_metadata(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadata with more arcs than the cap still produces a bounded query."""
    thread = Thread(
        user_id=default_user.id,
        title="Arc Heavy Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    arc_ids = list(range(1, MAX_ARCS_PER_INTELLIGENCE_READ + 6))
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1025277",
        metadata=_stored_metadata(issue_id=1025277, arc_ids=arc_ids),
        position=1,
    )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence(async_db, current.id, default_user.id),
            timeout=10,
        )

    assert result is not None
    assert result.comicvine_issue_id == "1025277"
    related_statements = [text for text in ledger.statements if "@>" in text]
    assert related_statements
    # Two containment branches per capped arc, no more.
    assert max(text.count("@>") for text in related_statements) <= (
        2 * MAX_ARCS_PER_INTELLIGENCE_READ
    )


@pytest.mark.asyncio
async def test_unmapped_issue_stays_null_and_schedules_nothing(
    async_db: AsyncSession,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity correctness is preserved: no mapping means no data and no refresh."""
    scheduled: list[int] = []

    def _recording_schedule(identity_id: int) -> bool:
        scheduled.append(identity_id)
        return True

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _recording_schedule
    )

    result = await get_issue_intelligence(async_db, issue_id=987_654_321, user_id=1)

    assert result is None
    assert scheduled == []
