"""PostgreSQL integration coverage for the guarded Step 22 B.P.R.D. migration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.event import Event
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.bprd_production_migration import (
    BPRDMigrationSpec,
    IssueExpectation,
    LegacyEdgeExpectation,
    MigrationInvariantError,
    ThreadExpectation,
    apply_bprd_migration,
    build_bprd_dry_run,
    rollback_bprd_migration,
)
from comic_pile.dependencies import refresh_user_blocked_status
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


async def _make_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    active: bool,
) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=queue_position,
        status="active" if active else "completed",
        user_id=user_id,
        total_issues=0,
        reading_progress="in_progress" if active else "completed",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _add_issue(
    db: AsyncSession,
    *,
    thread: Thread,
    issue_number: str,
    position: int,
    read: bool,
) -> Issue:
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="read" if read else "unread",
        read_at=datetime.now(UTC) if read else None,
    )
    db.add(issue)
    await db.flush()
    thread.total_issues = (thread.total_issues or 0) + 1
    if not read:
        thread.issues_remaining = (thread.issues_remaining or 0) + 1
        if thread.next_unread_issue_id is None:
            thread.next_unread_issue_id = issue.id
    return issue


async def _seed_migration_shape(
    db: AsyncSession,
) -> tuple[BPRDMigrationSpec, Thread, Thread]:
    user = await get_or_create_user_async(db)
    plague = await _make_thread(
        db,
        user_id=user.id,
        title="B.P.R.D.: PLAGUE OF FROGS",
        queue_position=100,
        active=False,
    )
    dead = await _make_thread(
        db,
        user_id=user.id,
        title="B.P.R.D.: THE DEAD",
        queue_position=101,
        active=False,
    )
    black_flame = await _make_thread(
        db,
        user_id=user.id,
        title="B.P.R.D.: THE BLACK FLAME",
        queue_position=5,
        active=True,
    )
    war_on_frogs = await _make_thread(
        db,
        user_id=user.id,
        title="B.P.R.D.: WAR ON FROGS",
        queue_position=6,
        active=True,
    )

    plague_issues = [
        await _add_issue(
            db,
            thread=plague,
            issue_number=str(number),
            position=number,
            read=True,
        )
        for number in range(1, 6)
    ]
    dead_issues = [
        await _add_issue(
            db,
            thread=dead,
            issue_number=str(number),
            position=number,
            read=True,
        )
        for number in range(1, 7)
    ]
    black_issues = [
        await _add_issue(
            db,
            thread=black_flame,
            issue_number=str(number),
            position=number,
            read=number == 1,
        )
        for number in range(1, 7)
    ]
    wof_1 = await _add_issue(
        db,
        thread=war_on_frogs,
        issue_number="1",
        position=1,
        read=True,
    )
    revival = await _add_issue(
        db,
        thread=war_on_frogs,
        issue_number="Revival",
        position=2,
        read=True,
    )
    wof_2 = await _add_issue(
        db,
        thread=war_on_frogs,
        issue_number="2",
        position=3,
        read=True,
    )
    wof_4 = await _add_issue(
        db,
        thread=war_on_frogs,
        issue_number="4",
        position=4,
        read=True,
    )
    wof_3 = await _add_issue(
        db,
        thread=war_on_frogs,
        issue_number="3",
        position=5,
        read=False,
    )

    ordered = [
        *plague_issues,
        *dead_issues,
        black_issues[0],
        wof_1,
        revival,
        wof_2,
        wof_4,
        *black_issues[1:],
        wof_3,
    ]
    assert len(ordered) == 22

    edge_rows = [
        (plague_issues[-1], dead_issues[0], None),
        (dead_issues[-1], black_issues[0], None),
        (black_issues[0], wof_1, None),
        (wof_4, black_issues[1], "interleave one"),
        (black_issues[-1], wof_3, "interleave two"),
    ]
    legacy_expectations = []
    for source, target, note in edge_rows:
        dependency = Dependency(
            source_issue_id=source.id,
            target_issue_id=target.id,
            note=note,
        )
        db.add(dependency)
        await db.flush()
        rule = ContinuityRule(
            user_id=user.id,
            legacy_dependency_id=dependency.id,
            source_type="issue",
            source_id=source.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="item_read",
            note=note,
        )
        db.add(rule)
        await db.flush()
        legacy_expectations.append(
            LegacyEdgeExpectation(
                dependency.id,
                rule.id,
                source.id,
                target.id,
                note,
            )
        )

    group = DependencyGroup(user_id=user.id, name="B.P.R.D.: Plague of Frogs Era")
    db.add(group)
    await db.flush()
    for issue in ordered:
        db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"bprd-step22-{ordered[0].id}",
        metadata_json={},
    )
    db.add(identity)
    await db.flush()
    db.add(
        IssueExternalIdentityMapping(
            issue_id=ordered[0].id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="step22_test",
        )
    )
    db.add(
        Event(
            type="issue_read",
            timestamp=datetime.now(UTC),
            thread_id=plague.id,
            issue_id=ordered[0].id,
            issue_number=ordered[0].issue_number,
        )
    )
    await db.flush()
    await refresh_user_blocked_status(user.id, db)
    await db.commit()
    await db.refresh(black_flame)
    await db.refresh(war_on_frogs)

    threads = (plague, dead, black_flame, war_on_frogs)
    spec = BPRDMigrationSpec(
        user_id=user.id,
        plan_name="B.P.R.D.",
        issues=tuple(
            IssueExpectation(
                issue.id,
                issue.thread_id,
                next(thread.title for thread in threads if thread.id == issue.thread_id),
                issue.issue_number,
                issue.status,
            )
            for issue in ordered
        ),
        threads=tuple(
            ThreadExpectation(
                thread.id,
                thread.title,
                thread.status,
                thread.is_blocked,
                thread.next_unread_issue_id,
                thread.issues_remaining,
                thread.reading_progress,
            )
            for thread in threads
        ),
        legacy_edges=tuple(legacy_expectations),
        dependency_group_id=group.id,
    )
    return spec, black_flame, war_on_frogs


async def _bprd_pool(user_id: int, db: AsyncSession) -> list[Thread]:
    pool = await get_roll_pool(user_id, db)
    return [thread for thread in pool if thread.title.startswith("B.P.R.D.:")]


@pytest.mark.asyncio
async def test_step22_dry_run_is_read_only(async_db: AsyncSession) -> None:
    """Dry-run reports the exact plan without creating or deleting rows."""
    spec, _, _ = await _seed_migration_shape(async_db)
    plan_count_before = await async_db.scalar(
        select(func.count()).select_from(ContinuityPlan)
    )
    dependency_count_before = await async_db.scalar(
        select(func.count()).select_from(Dependency)
    )
    rule_count_before = await async_db.scalar(
        select(func.count()).select_from(ContinuityRule)
    )

    report = await build_bprd_dry_run(async_db, spec)

    assert report["ok"] is True, report["errors"]
    assert report["overlapping_plans"] == []
    assert len(report["legacy_dependencies"]) == 5
    assert len(report["legacy_rules"]) == 5
    assert report["dependency_group"]["ordered_membership_count"] == 0
    assert len(report["planned"]["nodes"]) == 22
    assert len(report["planned"]["rule_edges"]) == 21
    assert (
        await async_db.scalar(select(func.count()).select_from(ContinuityPlan))
        == plan_count_before
    )
    assert (
        await async_db.scalar(select(func.count()).select_from(Dependency))
        == dependency_count_before
    )
    assert (
        await async_db.scalar(select(func.count()).select_from(ContinuityRule))
        == rule_count_before
    )


@pytest.mark.asyncio
async def test_step22_apply_replaces_legacy_authority_and_preserves_roll(
    async_db: AsyncSession,
) -> None:
    """Apply replaces five legacy edges while preserving the active Roll boundary."""
    spec, black_flame, war_on_frogs = await _seed_migration_shape(async_db)
    before_pool = await _bprd_pool(spec.user_id, async_db)
    assert [thread.id for thread in before_pool] == [black_flame.id]
    assert war_on_frogs.is_blocked is True

    snapshot = await build_bprd_dry_run(async_db, spec)
    receipt = await apply_bprd_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.commit()

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    assert plan.ordering_mode == "strict_sequential"
    assert [node["ref_id"] for node in plan.nodes_json] == list(spec.issue_ids)
    assert receipt["plan_rule_count"] == 21
    assert receipt["issue_state_hash"] == snapshot["factual"]["issue_state_hash"]
    assert receipt["event_state_hash"] == snapshot["factual"]["event_state_hash"]
    assert receipt["identity_state_hash"] == snapshot["factual"]["identity_state_hash"]

    remaining_legacy = (
        await async_db.execute(
            select(Dependency.id).where(
                Dependency.id.in_([edge.dependency_id for edge in spec.legacy_edges])
            )
        )
    ).scalars().all()
    assert remaining_legacy == []

    ordered_memberships = await async_db.scalar(
        select(func.count())
        .select_from(DependencyGroupMembership)
        .where(
            DependencyGroupMembership.group_id == spec.dependency_group_id,
            DependencyGroupMembership.sequence_order.is_not(None),
        )
    )
    assert ordered_memberships == 0

    await async_db.refresh(black_flame)
    await async_db.refresh(war_on_frogs)
    assert black_flame.is_blocked is False
    assert war_on_frogs.is_blocked is True
    after_pool = await _bprd_pool(spec.user_id, async_db)
    assert [thread.id for thread in after_pool] == [black_flame.id]


@pytest.mark.asyncio
async def test_step22_rollback_restores_exact_legacy_edges(
    async_db: AsyncSession,
) -> None:
    """Rollback restores exact dependency/rule IDs and the original Roll boundary."""
    spec, black_flame, war_on_frogs = await _seed_migration_shape(async_db)
    snapshot = await build_bprd_dry_run(async_db, spec)
    receipt = await apply_bprd_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.commit()

    result = await rollback_bprd_migration(
        async_db,
        snapshot=snapshot,
        receipt=receipt,
        spec=spec,
    )
    await async_db.commit()

    assert result["restored_dependency_ids"] == sorted(
        edge.dependency_id for edge in spec.legacy_edges
    )
    assert await async_db.get(ContinuityPlan, receipt["plan_id"]) is None
    restored_rules = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.legacy_dependency_id.in_(
                    [edge.dependency_id for edge in spec.legacy_edges]
                )
            )
        )
    ).scalars().all()
    assert {rule.id for rule in restored_rules} == {
        edge.rule_id for edge in spec.legacy_edges
    }
    assert (
        result["factual"]["issue_state_hash"]
        == snapshot["factual"]["issue_state_hash"]
    )
    assert (
        result["factual"]["event_state_hash"]
        == snapshot["factual"]["event_state_hash"]
    )

    await async_db.refresh(black_flame)
    await async_db.refresh(war_on_frogs)
    assert black_flame.is_blocked is False
    assert war_on_frogs.is_blocked is True
    pool = await _bprd_pool(spec.user_id, async_db)
    assert [thread.id for thread in pool] == [black_flame.id]


@pytest.mark.asyncio
async def test_step22_rollback_refuses_after_reader_edits_plan(
    async_db: AsyncSession,
) -> None:
    """Rollback fails closed instead of overwriting reader changes to the plan."""
    spec, _, _ = await _seed_migration_shape(async_db)
    snapshot = await build_bprd_dry_run(async_db, spec)
    receipt = await apply_bprd_migration(async_db, snapshot=snapshot, spec=spec)
    await async_db.commit()

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    plan.name = "Reader edited this plan"
    await async_db.commit()

    with pytest.raises(MigrationInvariantError, match="edited after cutover"):
        await rollback_bprd_migration(
            async_db,
            snapshot=snapshot,
            receipt=receipt,
            spec=spec,
        )
    await async_db.rollback()

    assert await async_db.get(ContinuityPlan, receipt["plan_id"]) is not None
