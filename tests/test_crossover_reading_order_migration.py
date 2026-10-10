"""PostgreSQL coverage for the Crossover reader-order migration (#3038)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.crossover_reading_order_migration import (
    CrossoverReadingOrderSpec,
    MigrationInvariantError,
    apply_crossover_reading_order_migration,
    build_crossover_reading_order_dry_run,
    classify_crossover_group,
    crossover_content_hash,
    inventory_crossover_reader_orders,
)
from comic_pile.dependencies import refresh_user_blocked_status
from tests.conftest import get_or_create_user_async


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    status: str = "unread",
) -> tuple[Thread, Issue]:
    """Create one thread with a single issue."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="completed" if status == "read" else "active",
        total_issues=1,
        issues_remaining=0 if status == "read" else 1,
        reading_progress="completed" if status == "read" else "unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status=status,
        read_at=datetime.now(UTC) if status == "read" else None,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = None if status == "read" else issue.id
    await db.flush()
    return thread, issue


async def _crossover_group(
    db: AsyncSession,
    *,
    user_id: int,
    name: str,
    ordered_issue_ids: list[int],
    thread_member_ids: list[int] | None = None,
) -> DependencyGroup:
    """Create a crossover group with sequence_ordered issue memberships."""
    group = DependencyGroup(user_id=user_id, name=name)
    db.add(group)
    await db.flush()
    for position, issue_id in enumerate(ordered_issue_ids, start=1):
        db.add(
            DependencyGroupMembership(
                group_id=group.id,
                issue_id=issue_id,
                sequence_order=position,
            )
        )
    for thread_id in thread_member_ids or []:
        db.add(DependencyGroupMembership(group_id=group.id, thread_id=thread_id))
    await db.flush()
    return group


def _spec(
    user_id: int, group: DependencyGroup, issue_ids: list[int], name: str = "Migrated Plan"
) -> CrossoverReadingOrderSpec:
    ordered = [(0, issue_id, pos) for pos, issue_id in enumerate(issue_ids, start=1)]
    return CrossoverReadingOrderSpec(
        user_id=user_id,
        dependency_group_id=group.id,
        plan_name=name,
        expected_content_hash=crossover_content_hash(ordered),
        expected_positions=len(issue_ids),
    )


@pytest.mark.asyncio
async def test_classify_clean_group_is_safely_migratable(
    async_db: AsyncSession,
) -> None:
    """A clean ordered crossover group classifies as safely migratable."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "safely_migratable"
    assert result["position_count"] == 2
    assert [row["issue_id"] for row in result["ordered_positions"]] == [issue_a.id, issue_b.id]


@pytest.mark.asyncio
async def test_classify_group_without_order_is_not_reader_order(
    async_db: AsyncSession,
) -> None:
    """A group with no sequence_order memberships is not a reader order."""
    user = await get_or_create_user_async(async_db)
    group = DependencyGroup(user_id=user.id, name="Unordered")
    async_db.add(group)
    await async_db.flush()

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "not_reader_order"


@pytest.mark.asyncio
async def test_classify_duplicate_sequence_order_is_ambiguous(
    async_db: AsyncSession,
) -> None:
    """Duplicate sequence_order values fail closed to human review."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = DependencyGroup(user_id=user.id, name="Dup")
    async_db.add(group)
    await async_db.flush()
    async_db.add(
        DependencyGroupMembership(group_id=group.id, issue_id=issue_a.id, sequence_order=1)
    )
    async_db.add(
        DependencyGroupMembership(group_id=group.id, issue_id=issue_b.id, sequence_order=1)
    )
    await async_db.flush()

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "ambiguous"
    assert "duplicate" in result["reason"]


@pytest.mark.asyncio
async def test_classify_thread_level_member_is_ambiguous(
    async_db: AsyncSession,
) -> None:
    """Thread-level members cannot be ordered; they need human disposition."""
    user = await get_or_create_user_async(async_db)
    thread, issue = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    group = await _crossover_group(
        async_db,
        user_id=user.id,
        name="Mixed",
        ordered_issue_ids=[issue.id],
        thread_member_ids=[thread.id],
    )

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "ambiguous"


@pytest.mark.asyncio
async def test_classify_matching_plan_is_already_represented(
    async_db: AsyncSession,
) -> None:
    """An identical strict plan means there is nothing to migrate."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="Existing Plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
        nodes_json=[
            {
                "id": f"issue-{issue_a.id}",
                "node_type": "issue",
                "ref_id": issue_a.id,
                "lane_id": "main",
                "position": 0,
            },
            {
                "id": f"issue-{issue_b.id}",
                "node_type": "issue",
                "ref_id": issue_b.id,
                "lane_id": "main",
                "position": 1,
            },
        ],
    )
    async_db.add(plan)
    await async_db.flush()

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "already_represented"
    assert result["represented_by_plan_id"] == plan.id


@pytest.mark.asyncio
async def test_classify_overlapping_plan_needs_merge(
    async_db: AsyncSession,
) -> None:
    """Partial overlap with a plan stops for human reconciliation."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    _, issue_c = await _thread_issue(async_db, user_id=user.id, title="C", queue_position=3)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    async_db.add(
        ContinuityPlan(
            user_id=user.id,
            name="Partial Plan",
            ordering_mode="strict_sequential",
            lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
            nodes_json=[
                {
                    "id": f"issue-{issue_b.id}",
                    "node_type": "issue",
                    "ref_id": issue_b.id,
                    "lane_id": "main",
                    "position": 0,
                },
                {
                    "id": f"issue-{issue_c.id}",
                    "node_type": "issue",
                    "ref_id": issue_c.id,
                    "lane_id": "main",
                    "position": 1,
                },
            ],
        )
    )
    await async_db.flush()

    result = await classify_crossover_group(async_db, user_id=user.id, group_id=group.id)

    assert result["classification"] == "merge_needed"
    assert result["overlapping_plans"]


@pytest.mark.asyncio
async def test_inventory_lists_every_group_oldest_first(
    async_db: AsyncSession,
) -> None:
    """Inventory covers all user groups in creation order."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    first = await _crossover_group(
        async_db, user_id=user.id, name="First", ordered_issue_ids=[issue_a.id]
    )
    second = DependencyGroup(user_id=user.id, name="Second")
    async_db.add(second)
    await async_db.flush()

    inventory = await inventory_crossover_reader_orders(async_db, user_id=user.id)

    by_id = {row["group_id"]: row for row in inventory}
    assert by_id[first.id]["classification"] == "safely_migratable"
    assert by_id[second.id]["classification"] == "not_reader_order"
    assert [row["group_id"] for row in inventory] == sorted(by_id)


@pytest.mark.asyncio
async def test_dry_run_ok_and_snapshot_token_is_stable(
    async_db: AsyncSession,
) -> None:
    """A clean dry-run is ok and deterministic across runs."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    spec = _spec(user.id, group, [issue_a.id, issue_b.id])

    first = await build_crossover_reading_order_dry_run(async_db, spec)
    second = await build_crossover_reading_order_dry_run(async_db, spec)

    assert first["ok"] is True
    assert first["errors"] == []
    assert first["snapshot_token"] == second["snapshot_token"]
    assert first["planned"] is not None
    assert first["planned"]["adjacent_rule_count"] == 1
    assert len(first["planned"]["rules"]) == 1
    rule = first["planned"]["rules"][0]
    assert (rule["source_id"], rule["target_id"]) == (issue_a.id, issue_b.id)


@pytest.mark.asyncio
async def test_dry_run_detects_content_drift(async_db: AsyncSession) -> None:
    """A manifest hash mismatch fails the dry-run closed."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    spec = CrossoverReadingOrderSpec(
        user_id=user.id,
        dependency_group_id=group.id,
        plan_name="Migrated Plan",
        expected_content_hash="deadbeef",
        expected_positions=2,
    )

    report = await build_crossover_reading_order_dry_run(async_db, spec)

    assert report["ok"] is False
    assert any("content changed" in error for error in report["errors"])


@pytest.mark.asyncio
async def test_apply_creates_plan_rules_and_receipt(
    async_db: AsyncSession,
) -> None:
    """Apply creates exactly one plan with adjacency rules and a receipt."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    _, issue_c = await _thread_issue(async_db, user_id=user.id, title="C", queue_position=3)
    group = await _crossover_group(
        async_db,
        user_id=user.id,
        name="X-Over",
        ordered_issue_ids=[issue_a.id, issue_b.id, issue_c.id],
    )
    # Persist derived blocked state before the dry run, mirroring production
    # where the app refreshes it on every mutation. Apply re-runs the refresh
    # internally, so the fixture must start from settled state for the
    # post-apply reader-state invariant to hold.
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    spec = _spec(user.id, group, [issue_a.id, issue_b.id, issue_c.id])
    snapshot = await build_crossover_reading_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True

    receipt = await apply_crossover_reading_order_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.flush()

    assert receipt["already_applied"] is False
    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    assert plan.name == "Migrated Plan"
    assert plan.ordering_mode == "strict_sequential"
    refs = [
        int(node["ref_id"]) for node in sorted(plan.nodes_json, key=lambda n: int(n["position"]))
    ]
    assert refs == [issue_a.id, issue_b.id, issue_c.id]
    assert receipt["plan_rule_count"] == 2
    dependencies = list((await async_db.scalars(select(Dependency))).all())
    assert {(dep.source_issue_id, dep.target_issue_id) for dep in dependencies} == {
        (issue_a.id, issue_b.id),
        (issue_b.id, issue_c.id),
    }
    links = list((await async_db.scalars(select(ReadingPlanDependency))).all())
    assert {(link.plan_id, link.dependency_id) for link in links} == {
        (plan.id, dep.id) for dep in dependencies
    }
    assert receipt["affected_roll_eligible_thread_ids"] == [issue_a.thread_id]
    assert [issue_a.status, issue_b.status, issue_c.status] == ["unread"] * 3
    # Reader facts and legacy display memberships survive; blocking is derived.
    fresh_group = await async_db.get(DependencyGroup, group.id)
    assert fresh_group is not None
    memberships = list(
        (
            await async_db.execute(
                select(DependencyGroupMembership).where(
                    DependencyGroupMembership.group_id == group.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(m.sequence_order or 0 for m in memberships) == [1, 2, 3]


@pytest.mark.asyncio
async def test_apply_is_idempotent(async_db: AsyncSession) -> None:
    """Re-applying after a successful migration returns the existing plan."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    # See test_apply_creates_plan_rules_and_receipt: settle derived blocked
    # state before the dry run so apply's internal refresh is a no-op.
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()
    spec = _spec(user.id, group, [issue_a.id, issue_b.id])
    snapshot = await build_crossover_reading_order_dry_run(async_db, spec)
    first = await apply_crossover_reading_order_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.flush()

    before_ids = list((await async_db.scalars(select(Dependency.id))).all())
    assert len(before_ids) == 1
    rerun = await build_crossover_reading_order_dry_run(async_db, spec)
    assert rerun["classification"] == "already_represented"
    second = await apply_crossover_reading_order_migration(async_db, snapshot=rerun, spec=spec)

    assert second["already_applied"] is True
    assert second["plan_id"] == first["plan_id"]
    plans = list(
        (await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(plans) == 1
    deps = list((await async_db.scalars(select(Dependency))).all())
    assert [dep.id for dep in deps] == before_ids
    assert [(dep.source_issue_id, dep.target_issue_id) for dep in deps] == [
        (issue_a.id, issue_b.id)
    ]
    links = list((await async_db.scalars(select(ReadingPlanDependency))).all())
    assert [(link.plan_id, link.dependency_id) for link in links] == [
        (first["plan_id"], before_ids[0])
    ]


@pytest.mark.asyncio
async def test_apply_refuses_drifted_snapshot(async_db: AsyncSession) -> None:
    """Apply fails closed when live state moved since the dry-run."""
    user = await get_or_create_user_async(async_db)
    _, issue_a = await _thread_issue(async_db, user_id=user.id, title="A", queue_position=1)
    _, issue_b = await _thread_issue(async_db, user_id=user.id, title="B", queue_position=2)
    _, issue_c = await _thread_issue(async_db, user_id=user.id, title="C", queue_position=3)
    group = await _crossover_group(
        async_db, user_id=user.id, name="X-Over", ordered_issue_ids=[issue_a.id, issue_b.id]
    )
    spec = _spec(user.id, group, [issue_a.id, issue_b.id])
    snapshot = await build_crossover_reading_order_dry_run(async_db, spec)

    async_db.add(
        DependencyGroupMembership(group_id=group.id, issue_id=issue_c.id, sequence_order=99)
    )
    await async_db.flush()

    with pytest.raises(MigrationInvariantError, match="live state changed"):
        await apply_crossover_reading_order_migration(async_db, snapshot=snapshot, spec=spec)
