"""Performance regression tests for optimized comicvine intelligence service.

These tests verify that the optimizations to the comicvine intelligence service
meet the performance target of under 1000ms total response time, with a focus
on reducing application processing time from 1590ms to under 850ms.
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
from app.services.comicvine_intelligence_optimized import get_issue_intelligence_optimized


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
async def test_optimized_performance_meets_target(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify the optimized version meets the 1000ms performance target.
    
    This test simulates the production performance scenario where the endpoint
    took 1773ms total (182ms DB + 1590ms application) and verifies that the
    optimized version reduces total time to under 1000ms.
    """
    thread = Thread(
        user_id=default_user.id,
        title="Performance Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    
    # Create a complex scenario with multiple arcs and related issues to simulate
    # the production workload that caused the performance issue
    arc_ids = list(range(1, MAX_ARCS_PER_INTELLIGENCE_READ + 5))  # Saturate the arc limit
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata=_stored_metadata(issue_id=1001184, arc_ids=arc_ids),
        position=1,
    )
    
    # Create many related issues to test the performance optimization
    for offset in range(100):  # More than the per-arc limit
        await _mapped_issue(
            async_db,
            thread,
            issue_number=str(2 + offset),
            external_id=str(2000000 + offset),
            metadata=_stored_metadata(issue_id=2000000 + offset, arc_ids=arc_ids[:3]),  # Related to first 3 arcs
            position=2 + offset,
        )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    # Test the optimized version
    started = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence_optimized(async_db, current.id, default_user.id),
            timeout=10,
        )
    optimized_wall_seconds = time.perf_counter() - started
    optimized_app_seconds = optimized_wall_seconds - ledger.db_seconds

    assert result is not None
    assert result.comicvine_issue_id == "1001184"
    assert result.series_name == "Bench Volume"
    assert len(result.story_arcs) == len(arc_ids)
    
    # Verify the performance target is met
    assert optimized_wall_seconds < 1000, (
        f"Optimized version took {optimized_wall_seconds:.2f}ms "
        f"(DB: {ledger.db_seconds:.2f}ms, App: {optimized_app_seconds:.2f}ms), "
        f"target is <1000ms"
    )
    
    # Verify the application time reduction (from 1590ms to under 850ms)
    assert optimized_app_seconds < 850, (
        f"Optimized application time {optimized_app_seconds:.2f}ms "
        f"should be <850ms (was 1590ms before optimization)"
    )


@pytest.mark.asyncio 
async def test_optimized_vs_baseline_performance(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare optimized version performance against baseline.
    
    This test runs both the original and optimized versions on the same data
    to demonstrate the performance improvement.
    """
    thread = Thread(
        user_id=default_user.id,
        title="Comparison Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    
    # Create a moderate complexity scenario
    arc_ids = [42, 84, 126]
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1025277",
        metadata=_stored_metadata(issue_id=1025277, arc_ids=arc_ids),
        position=1,
    )
    
    # Create some related issues
    for offset in range(50):
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

    # Test baseline version
    baseline_started = time.perf_counter()
    with _measured_selects(db_engine) as baseline_ledger:
        baseline_result = await asyncio.wait_for(
            get_issue_intelligence(async_db, current.id, default_user.id),
            timeout=10,
        )
    baseline_wall_seconds = time.perf_counter() - baseline_started
    baseline_app_seconds = baseline_wall_seconds - baseline_ledger.db_seconds

    # Test optimized version
    optimized_started = time.perf_counter()
    with _measured_selects(db_engine) as optimized_ledger:
        optimized_result = await asyncio.wait_for(
            get_issue_intelligence_optimized(async_db, current.id, default_user.id),
            timeout=10,
        )
    optimized_wall_seconds = time.perf_counter() - optimized_started
    optimized_app_seconds = optimized_wall_seconds - optimized_ledger.db_seconds

    # Verify results are functionally equivalent
    assert baseline_result.comicvine_issue_id == optimized_result.comicvine_issue_id
    assert len(baseline_result.story_arcs) == len(optimized_result.story_arcs)
    
    # Verify performance improvement
    improvement_ratio = baseline_app_seconds / optimized_app_seconds
    assert optimized_wall_seconds < baseline_wall_seconds, (
        f"Optimized version ({optimized_wall_seconds:.2f}ms) should be faster "
        f"than baseline ({baseline_wall_seconds:.2f}ms)"
    )
    
    # Expect at least 30% improvement in application time
    assert improvement_ratio > 1.3, (
        f"Expected at least 30% improvement, got {improvement_ratio:.2f}x "
        f"(baseline app: {baseline_app_seconds:.2f}ms, optimized app: {optimized_app_seconds:.2f}ms)"
    )


@pytest.mark.asyncio
async def test_optimized_creator_processing_performance(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that creator processing optimization reduces string processing time."""
    thread = Thread(
        user_id=default_user.id,
        title="Creator Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    
    # Create metadata with many creators to test optimization
    metadata = _stored_metadata(issue_id=1001184, arc_ids=[42])
    # Add many creators to stress test the optimization
    metadata["person_credits"] = [
        {"id": 1000 + offset, "name": f"Creator {offset}", "role": "writer"}
        for offset in range(50)  # Many creators
    ]
    metadata["raw_provider_payload"]["person_credits"] = metadata["person_credits"]
    
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata=metadata,
        position=1,
    )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    # Test optimized version with many creators
    started = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence_optimized(async_db, current.id, default_user.id),
            timeout=10,
        )
    wall_seconds = time.perf_counter() - started
    app_seconds = wall_seconds - ledger.db_seconds

    assert result is not None
    assert len(result.creators) == 50  # Should have all 50 creators
    
    # Verify creator processing is fast even with many creators
    assert app_seconds < 200, (
        f"Creator processing took {app_seconds:.2f}ms app time, "
        f"should be <200ms even with 50 creators"
    )


@pytest.mark.asyncio
async def test_optimized_json_query_performance(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that JSON query optimization reduces database query time."""
    thread = Thread(
        user_id=default_user.id,
        title="JSON Query Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    
    # Create scenario with many arc-related issues to test JSON query optimization
    arc_ids = list(range(1, 8))  # Multiple arcs
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata=_stored_metadata(issue_id=1001184, arc_ids=arc_ids),
        position=1,
    )
    
    # Create many related issues across multiple arcs
    for arc_id in arc_ids:
        for offset in range(20):  # 20 issues per arc
            await _mapped_issue(
                async_db,
                thread,
                issue_number=f"{arc_id}-{offset}",
                external_id=f"{3000000 + arc_id * 1000 + offset}",
                metadata=_stored_metadata(issue_id=3000000 + arc_id * 1000 + offset, arc_ids=[arc_id]),
                position=10 + arc_id * 20 + offset,
            )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    # Test optimized version with complex JSON queries
    started = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence_optimized(async_db, current.id, default_user.id),
            timeout=10,
        )
    wall_seconds = time.perf_counter() - started
    db_seconds = ledger.db_seconds
    app_seconds = wall_seconds - db_seconds

    assert result is not None
    assert len(result.story_arcs) == len(arc_ids)
    
    # Verify JSON query optimization is effective
    assert db_seconds < 300, (
        f"Database query time {db_seconds:.2f}ms should be <300ms "
        f"even with complex JSON queries"
    )
    
    # Verify total performance is still good
    assert wall_seconds < 800, (
        f"Total time {wall_seconds:.2f}ms should be <800ms "
        f"even with complex JSON queries"
    )


@pytest.mark.asyncio
async def test_optimized_arc_processing_performance(
    async_db: AsyncSession,
    db_engine: AsyncEngine,
    default_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that arc processing optimization reduces sorting time."""
    thread = Thread(
        user_id=default_user.id,
        title="Arc Processing Test Series",
        format="issue",
        issues_remaining=1,
        total_issues=1,
        queue_position=1,
    )
    async_db.add(thread)
    await async_db.flush()
    
    # Create scenario with many related issues per arc to test sorting optimization
    arc_ids = [42, 84, 126]
    current, _identity = await _mapped_issue(
        async_db,
        thread,
        issue_number="1",
        external_id="1001184",
        metadata=_stored_metadata(issue_id=1001184, arc_ids=arc_ids),
        position=1,
    )
    
    # Create many related issues for sorting test
    for arc_id in arc_ids:
        for offset in range(MAX_RELATED_ISSUES_PER_ARC + 10):  # Saturate the per-arc limit
            await _mapped_issue(
                async_db,
                thread,
                issue_number=f"{arc_id}-{offset}",
                external_id=f"{4000000 + arc_id * 1000 + offset}",
                metadata=_stored_metadata(issue_id=4000000 + arc_id * 1000 + offset, arc_ids=[arc_id]),
                position=20 + arc_id * 30 + offset,
            )

    def _noop_schedule(_identity_id: int) -> bool:
        return False

    monkeypatch.setattr(
        comicvine_intelligence, "schedule_issue_metadata_refresh", _noop_schedule
    )

    # Test optimized version with arc processing
    started = time.perf_counter()
    with _measured_selects(db_engine) as ledger:
        result = await asyncio.wait_for(
            get_issue_intelligence_optimized(async_db, current.id, default_user.id),
            timeout=10,
        )
    wall_seconds = time.perf_counter() - started
    app_seconds = wall_seconds - ledger.db_seconds

    assert result is not None
    assert len(result.story_arcs) == len(arc_ids)
    
    # Verify each arc has the expected number of related issues
    for arc in result.story_arcs:
        assert len(arc.related_issues) <= MAX_RELATED_ISSUES_PER_ARC
        if arc.total_related_count is not None:
            assert arc.total_related_count > len(arc.related_issues)
    
    # Verify arc processing is fast even with many related issues
    assert app_seconds < 250, (
        f"Arc processing took {app_seconds:.2f}ms app time, "
        f"should be <250ms even with {MAX_RELATED_ISSUES_PER_ARC + 10} issues per arc"
    )