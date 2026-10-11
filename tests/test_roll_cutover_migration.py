"""Tests for the #2553 canonical Dependency backfill migration (c25530000001).

The migration persists one canonical Dependency edge per rule-native
ContinuityRule (item_read directly, converged expanded per prerequisite),
links edges to their owning Reading Plans with ownership validation, and
aborts on any rule that cannot compile to issue-level edges.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.thread import Thread
from app.models.user import User
from app.services import canonical_backfill as mig


def _sync_connection() -> sa.Connection:
    """Open a sync psycopg connection to the test database for migration calls."""
    url = os.environ["TEST_DATABASE_URL"].replace("postgresql+asyncpg", "postgresql+psycopg")
    engine = sa.create_engine(url)
    return engine.connect()


async def _user(db: AsyncSession, username: str) -> User:
    user = User(username=username, created_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    return user


async def _thread_with_issues(
    db: AsyncSession, user_id: int, title: str, numbers: list[str]
) -> tuple[Thread, list[Issue]]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=1,
        status="active",
        total_issues=len(numbers),
        issues_remaining=len(numbers),
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues = []
    for position, number in enumerate(numbers, start=1):
        issue = Issue(thread_id=thread.id, issue_number=number, position=position, status="unread")
        db.add(issue)
        issues.append(issue)
    await db.flush()
    thread.next_unread_issue_id = issues[0].id
    await db.flush()
    return thread, issues


async def _plan(db: AsyncSession, user_id: int, name: str) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
    )
    db.add(plan)
    await db.flush()
    return plan


async def _clean(db: AsyncSession) -> None:
    for model in (ReadingPlanDependency, ContinuityRule, Dependency, ContinuityPlan):
        await db.execute(sa.delete(model))
    await db.commit()


@pytest.fixture
async def _isolated_migration_data(async_db_committed: AsyncSession):
    """Provide a committed session and clean migration tables before and after."""
    await _clean(async_db_committed)
    try:
        yield async_db_committed
    finally:
        await _clean(async_db_committed)


@pytest.mark.asyncio
async def test_backfill_creates_edges_and_validated_plan_links(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Rule-native rules become edges; plan links require same-user ownership."""
    db = _isolated_migration_data

    user1 = await _user(db, "cutover-user-1")
    user2 = await _user(db, "cutover-user-2")
    plan1 = await _plan(db, user1.id, "User 1 Plan")
    plan2 = await _plan(db, user2.id, "User 2 Plan")
    _, (a1, a2) = await _thread_with_issues(db, user1.id, "Alpha", ["1", "2"])
    _, (b1, b2) = await _thread_with_issues(db, user1.id, "Beta", ["1", "2"])
    _, (c1, c2) = await _thread_with_issues(db, user2.id, "Gamma", ["1", "2"])

    # Existing edge + mirror rule: the edge already exists, so the rule is skipped.
    existing = Dependency(source_issue_id=a1.id, target_issue_id=a2.id, note="existing")
    db.add(existing)
    await db.flush()

    db.add_all(
        [
            # Plan-owned item_read -> edge + plan link.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=b1.id,
                satisfaction_type="item_read",
                note=f"continuity-plan:{plan1.id}",
            ),
            # Standalone item_read -> edge, no plan link.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a2.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="item_read",
            ),
            # Mirror of an existing edge -> skipped entirely.
            ContinuityRule(
                user_id=user1.id,
                legacy_dependency_id=existing.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=a2.id,
                satisfaction_type="item_read",
            ),
            # Converged rule -> one edge per prerequisite; both duplicates
            # already exist from the item_read rules above, so nothing new,
            # but both get plan links.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=b2.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="converged",
                convergence_targets=[
                    {"type": "issue", "id": a1.id},
                    {"type": "issue", "id": a2.id},
                ],
                note=f"continuity-plan:{plan1.id}",
            ),
            # Converged rule listing its own target -> self-edge skipped.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=b1.id,
                target_type="issue",
                target_id=b1.id,
                satisfaction_type="converged",
                convergence_targets=[
                    {"type": "issue", "id": b1.id},
                    {"type": "issue", "id": a2.id},
                ],
            ),
            # Cross-user plan note -> edge created, plan link skipped.
            ContinuityRule(
                user_id=user2.id,
                source_type="issue",
                source_id=c1.id,
                target_type="issue",
                target_id=c2.id,
                satisfaction_type="item_read",
                note=f"continuity-plan:{plan1.id}",
            ),
            # Dangling plan note -> edge created, plan link skipped.
            ContinuityRule(
                user_id=user1.id,
                source_type="issue",
                source_id=a1.id,
                target_type="issue",
                target_id=b2.id,
                satisfaction_type="item_read",
                note="continuity-plan:999999",
            ),
        ]
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        mig.drop_mirror_trigger(conn)
        item_inserted, _ = mig.backfill_item_read_edges(conn)
        conv_inserted, _, conv_self = mig.backfill_converged_edges(conn)
        links_created, links_skipped = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    # item_read: r1 (a1->b1), r2 (a2->b2), r6 (c1->c2), r7 (a1->b2) = 4 new edges.
    assert item_inserted == 4
    # Converged: both of r4's edges already exist (duplicates of item_read
    # edges); r5 contributes a2->b1, and the b1->b1 self-edge is skipped.
    assert conv_inserted == 1
    assert conv_self == 1

    edges = {
        (source_issue_id, target_issue_id): note
        for source_issue_id, target_issue_id, note in await db.execute(
            sa.select(Dependency.source_issue_id, Dependency.target_issue_id, Dependency.note)
        )
    }
    assert (edges[(a1.id, b1.id)] or "").startswith("canonical:rule-backfill:")
    assert (edges[(c1.id, c2.id)] or "").startswith("canonical:rule-backfill:")
    assert (b1.id, b1.id) not in edges  # self-edge never persisted

    links = {
        (plan_id, dependency_id)
        for plan_id, dependency_id in await db.execute(
            sa.select(ReadingPlanDependency.plan_id, ReadingPlanDependency.dependency_id)
        )
    }
    edge_ids = {
        (s, t): dep_id
        for dep_id, s, t in await db.execute(
            sa.select(Dependency.id, Dependency.source_issue_id, Dependency.target_issue_id)
        )
    }
    # Plan-owned rules link their edges to the owning plan.
    assert (plan1.id, edge_ids[(a1.id, b1.id)]) in links
    assert (plan1.id, edge_ids[(a1.id, b2.id)]) in links
    assert (plan1.id, edge_ids[(a2.id, b2.id)]) in links
    # The converged rule without a plan note creates an edge but no link.
    assert (plan1.id, edge_ids[(a2.id, b1.id)]) not in links
    # Cross-user and dangling plan notes never produce links.
    assert (plan1.id, edge_ids[(c1.id, c2.id)]) not in links
    assert (plan2.id, edge_ids[(c1.id, c2.id)]) not in links
    assert links_created == 3
    assert len(links_skipped) == 2

    # Mirror rule left no trace: no new edge, no link for the existing one.
    assert edges[(a1.id, a2.id)] == "existing"


@pytest.mark.asyncio
async def test_validation_aborts_on_dangling_rule(_isolated_migration_data: AsyncSession) -> None:
    """A rule referencing a missing issue aborts the migration with its ID."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-dangling-user")
    _, (a1, _) = await _thread_with_issues(db, user.id, "Delta", ["1", "2"])
    bad = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=a1.id,
        target_type="issue",
        target_id=999999,
        satisfaction_type="item_read",
    )
    db.add(bad)
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="missing source or target issues"):
            mig.validate_compilable_rules(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backfill_is_idempotent(_isolated_migration_data: AsyncSession) -> None:
    """Running the backfill twice creates no duplicate edges or links."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-idempotent-user")
    plan = await _plan(db, user.id, "Idempotent Plan")
    _, (a1,) = await _thread_with_issues(db, user.id, "Epsilon", ["1"])
    _, (b1,) = await _thread_with_issues(db, user.id, "Zeta", ["1"])
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
            note=f"continuity-plan:{plan.id}",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        first_edges, _ = mig.backfill_item_read_edges(conn)
        first_links, _ = mig.link_plan_provenance(conn)
        second_edges, _ = mig.backfill_item_read_edges(conn)
        second_links, _ = mig.link_plan_provenance(conn)
        conn.commit()
    finally:
        conn.close()

    assert first_edges == 1
    assert first_links == 1
    assert second_edges == 0
    assert second_links == 0


@pytest.mark.asyncio
async def test_validation_aborts_on_cross_user_issue_reference(
    _isolated_migration_data: AsyncSession,
) -> None:
    """A rule pointing at another user's issues aborts (clone-provenance hazard)."""
    db = _isolated_migration_data

    owner = await _user(db, "cutover-owner-user")
    other = await _user(db, "cutover-other-user")
    _, (a1,) = await _thread_with_issues(db, owner.id, "Theta", ["1"])
    _, (b1,) = await _thread_with_issues(db, other.id, "Iota", ["1"])
    db.add(
        ContinuityRule(
            user_id=owner.id,
            source_type="issue",
            source_id=a1.id,
            target_type="issue",
            target_id=b1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="different user than the rule"):
            mig.validate_compilable_rules(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_validation_aborts_on_non_issue_endpoints(
    _isolated_migration_data: AsyncSession,
) -> None:
    """An item_read rule with thread-level endpoints aborts the migration."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-endpoint-user")
    thread, (a1,) = await _thread_with_issues(db, user.id, "Kappa", ["1"])
    db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="crossover",
            source_id=thread.id,
            target_type="issue",
            target_id=a1.id,
            satisfaction_type="item_read",
        )
    )
    await db.commit()

    conn = _sync_connection()
    try:
        with pytest.raises(RuntimeError, match="non-issue endpoints"):
            mig.validate_compilable_rules(conn)
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_backfill_scales_to_hundreds_of_rules(
    _isolated_migration_data: AsyncSession,
) -> None:
    """Set-based backfill handles a few hundred rules without per-row Python."""
    db = _isolated_migration_data

    user = await _user(db, "cutover-scale-user")
    # 10 threads x 10 issues; chain issue i -> issue i+1 across the whole set.
    all_issues: list[Issue] = []
    for t in range(10):
        _, issues = await _thread_with_issues(
            db, user.id, f"ScaleThread{t}", [str(n) for n in range(10)]
        )
        all_issues.extend(issues)
    db.add_all(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=all_issues[i].id,
            target_type="issue",
            target_id=all_issues[i + 1].id,
            satisfaction_type="item_read",
        )
        for i in range(len(all_issues) - 1)
    )
    await db.commit()

    conn = _sync_connection()
    try:
        mig.validate_compilable_rules(conn)
        inserted, skipped = mig.backfill_item_read_edges(conn)
        conn.commit()
    finally:
        conn.close()

    assert inserted == len(all_issues) - 1
    assert skipped == 0
