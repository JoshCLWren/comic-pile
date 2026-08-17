"""Regression coverage for transitive continuity prerequisite traversal."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.continuity_chains as chains
from app.continuity_chains import resolve_continuity_chains
from app.continuity_readiness import SNAPSHOT_SESSION_KEY, _load_snapshot
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one active thread with one unread issue."""
    thread = Thread(
        title=f"Chain {suffix}",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    thread.next_unread_issue_id = issue.id
    return issue


def _item_rule(*, user_id: int, source_id: int, target_id: int) -> ContinuityRule:
    """Create one issue-to-issue item-read rule."""
    return ContinuityRule(
        user_id=user_id,
        source_type="issue",
        source_id=source_id,
        target_type="issue",
        target_id=target_id,
        satisfaction_type="item_read",
    )


@pytest.mark.asyncio
async def test_transitive_chain_recommends_first_readable_leaf(async_db: AsyncSession) -> None:
    """A blocked by B and B by C recommends C while preserving the full chain."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="A")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="B")
    issue_c = await _make_issue(async_db, user_id=user.id, suffix="C")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=issue_b.id, target_id=issue_a.id),
            _item_rule(user_id=user.id, source_id=issue_c.id, target_id=issue_b.id),
        ]
    )
    await async_db.commit()

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=issue_a.id,
    )

    assert result.direct_blockers[0].source_id == issue_b.id
    assert [[node.node_id for node in path] for path in result.chains] == [
        [issue_b.id, issue_c.id]
    ]
    assert [node.node_id for node in result.readable_prerequisites] == [issue_c.id]
    assert result.diagnostics == ()


@pytest.mark.asyncio
async def test_branching_chain_is_deterministic_and_preserves_every_leaf(
    async_db: AsyncSession,
) -> None:
    """Multiple prerequisite branches return stable paths and unique readable leaves."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="target")
    left = await _make_issue(async_db, user_id=user.id, suffix="left")
    right = await _make_issue(async_db, user_id=user.id, suffix="right")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=right.id, target_id=target.id),
            _item_rule(user_id=user.id, source_id=left.id, target_id=target.id),
        ]
    )
    await async_db.commit()

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=target.id,
    )

    assert [path[0].node_id for path in result.chains] == sorted([left.id, right.id])
    assert [node.node_id for node in result.readable_prerequisites] == sorted(
        [left.id, right.id]
    )


@pytest.mark.asyncio
async def test_legacy_cycle_returns_structured_diagnostic_instead_of_recursing(
    async_db: AsyncSession,
) -> None:
    """Malformed legacy cycles terminate with a structured cycle diagnostic."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="cycle-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="cycle-b")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=issue_b.id, target_id=issue_a.id),
            _item_rule(user_id=user.id, source_id=issue_a.id, target_id=issue_b.id),
        ]
    )
    await async_db.commit()

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=issue_a.id,
    )

    assert result.chains == ()
    assert result.readable_prerequisites == ()
    assert result.diagnostics[0].code == "cycle_detected"


@pytest.mark.asyncio
async def test_traversal_node_budget_returns_structured_diagnostic(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Traversal stops at the configured node budget instead of expanding indefinitely."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="budget-target")
    middle = await _make_issue(async_db, user_id=user.id, suffix="budget-middle")
    leaf = await _make_issue(async_db, user_id=user.id, suffix="budget-leaf")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=middle.id, target_id=target.id),
            _item_rule(user_id=user.id, source_id=leaf.id, target_id=middle.id),
        ]
    )
    await async_db.commit()
    monkeypatch.setattr(chains, "MAX_TRAVERSAL_NODES", 1)

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=target.id,
    )

    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "node_limit_exceeded"
    assert diagnostic.node_id == leaf.id
    assert diagnostic.limit == 1


@pytest.mark.asyncio
async def test_traversal_depth_budget_returns_structured_diagnostic(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deep chains stop at the configured depth with an explicit diagnostic."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="depth-target")
    middle = await _make_issue(async_db, user_id=user.id, suffix="depth-middle")
    leaf = await _make_issue(async_db, user_id=user.id, suffix="depth-leaf")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=middle.id, target_id=target.id),
            _item_rule(user_id=user.id, source_id=leaf.id, target_id=middle.id),
        ]
    )
    await async_db.commit()
    monkeypatch.setattr(chains, "MAX_TRAVERSAL_DEPTH", 0)

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=target.id,
    )

    diagnostic = result.diagnostics[0]
    assert diagnostic.code == "depth_limit_exceeded"
    assert diagnostic.node_id == leaf.id
    assert diagnostic.limit == 0


@pytest.mark.asyncio
async def test_large_branching_graph_resolves_with_stable_order(async_db: AsyncSession) -> None:
    """A realistically broad graph resolves in memory without losing prerequisite branches."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="large-target")
    prerequisites = [
        await _make_issue(async_db, user_id=user.id, suffix=f"large-{index}")
        for index in range(100)
    ]
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=issue.id, target_id=target.id)
            for issue in reversed(prerequisites)
        ]
    )
    await async_db.commit()

    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=target.id,
    )

    expected_ids = sorted(issue.id for issue in prerequisites)
    assert [path[0].node_id for path in result.chains] == expected_ids
    assert [node.node_id for node in result.readable_prerequisites] == expected_ids
    assert result.diagnostics == ()


@pytest.mark.asyncio
async def test_snapshot_caching_prevents_duplicate_loads(async_db: AsyncSession) -> None:
    """Multiple continuity calculations in one session reuse the same snapshot."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="cache-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="cache-b")
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=issue_b.id,
            target_type="issue",
            target_id=issue_a.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    # First call loads the snapshot and writes it to the session cache
    snapshot1 = await _load_snapshot(async_db, user.id)
    assert snapshot1.query_count == 6  # 6 bounded queries
    assert snapshot1.rows_loaded > 0

    # Verify the snapshot was cached in the session's info dict
    assert SNAPSHOT_SESSION_KEY in async_db.info
    session_cache = async_db.info[SNAPSHOT_SESSION_KEY]
    assert user.id in session_cache
    assert session_cache[user.id] is snapshot1

    # Second call should return the cached snapshot (proven by object identity,
    # which differs from an equivalent-but-distinct reload only if the cache works)
    snapshot2 = await _load_snapshot(async_db, user.id)
    assert snapshot2 is snapshot1
    assert snapshot2.query_count == snapshot1.query_count
    assert snapshot2.rows_loaded == snapshot1.rows_loaded

    # Verify traversal also uses cached snapshot
    result = await resolve_continuity_chains(
        async_db,
        user_id=user.id,
        node_type="issue",
        node_id=issue_a.id,
    )
    assert result.direct_blockers[0].source_id == issue_b.id


@pytest.mark.asyncio
async def test_snapshot_query_count_matches_bounded_queries(async_db: AsyncSession) -> None:
    """Snapshot query count matches the expected number of bounded queries."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="count-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="count-b")
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=issue_b.id,
            target_type="issue",
            target_id=issue_a.id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    snapshot = await _load_snapshot(async_db, user.id)
    # 6 queries: threads, issues, groups, memberships, rules, selected_members
    assert snapshot.query_count == 6
    # At minimum we loaded the two threads, two issues, and one rule
    assert snapshot.rows_loaded >= 5


@pytest.mark.asyncio
async def test_snapshot_cache_is_per_user(async_db: AsyncSession) -> None:
    """Snapshot cache is keyed by user_id and does not leak across users."""
    user1 = await get_or_create_user_async(async_db, username="cache_test_user1")
    user2 = await get_or_create_user_async(async_db, username="cache_test_user2")
    issue1 = await _make_issue(async_db, user_id=user1.id, suffix="user1")
    issue2 = await _make_issue(async_db, user_id=user2.id, suffix="user2")
    await async_db.commit()

    snapshot1 = await _load_snapshot(async_db, user1.id)
    snapshot2 = await _load_snapshot(async_db, user2.id)

    assert snapshot1 is not snapshot2
    assert issue1.id in snapshot1.issues
    assert issue1.id not in snapshot2.issues
    assert issue2.id in snapshot2.issues
    assert issue2.id not in snapshot1.issues


@pytest.mark.asyncio
async def test_large_graph_query_count_does_not_grow_with_node_count(
    async_db: AsyncSession,
) -> None:
    """Query count stays constant (6) regardless of graph size within bounds."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="growth-target")
    prerequisites = [
        await _make_issue(async_db, user_id=user.id, suffix=f"growth-{index}")
        for index in range(50)
    ]
    async_db.add_all(
        [
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=issue.id,
                target_type="issue",
                target_id=target.id,
                satisfaction_type="item_read",
            )
            for issue in prerequisites
        ]
    )
    await async_db.commit()

    snapshot = await _load_snapshot(async_db, user.id)
    # Query count should remain 6 even with 50 prerequisite issues
    assert snapshot.query_count == 6
    # Rows loaded grows with data but query count is bounded
    assert snapshot.rows_loaded >= 52  # 50 issues + target + at least 1 thread
