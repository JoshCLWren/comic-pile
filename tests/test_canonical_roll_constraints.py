"""Canonical authoring and deployment must agree with Roll and explanations."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.sql import Executable
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.canonical_constraints import synchronize_canonical_constraints
from app.services.continuity_graph import issue_readiness, load_snapshot
from app.services.continuity_plan_writer import replace_compiled_rules
from comic_pile.dependencies import get_blocking_explanations, refresh_user_blocked_status
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


async def make_issue(db: AsyncSession, user_id: int, title: str, number: str) -> Issue:
    """Create one active natural Thread frontier."""
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        status="active",
        total_issues=1,
        issues_remaining=1,
        queue_position=1,
        reading_progress="unstarted",
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number=number, position=1, status="unread")
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    return issue


def node(issue: Issue, position: int) -> ContinuityPlanNode:
    """Create an issue-only authoring node."""
    return ContinuityPlanNode(
        id=f"issue-{issue.id}",
        node_type="issue",
        ref_id=issue.id,
        lane_id="main",
        position=position,
        convergence_gate=[],
    )


@pytest.mark.asyncio
async def test_strict_plan_gates_roll_and_readiness_with_canonical_dependencies(
    async_db: AsyncSession,
) -> None:
    """Starman #55 gates JSA #1 from persisted hard intent, with matching copy."""
    user = await get_or_create_user_async(async_db)
    source = await make_issue(async_db, user.id, "Starman", "55")
    target = await make_issue(async_db, user.id, "JSA", "1")
    nodes = [node(source, 0), node(target, 1)]
    plan = ContinuityPlan(
        user_id=user.id,
        name="Hard starting gate",
        ordering_mode="strict_sequential",
        lanes_json=[],
        nodes_json=[item.model_dump() for item in nodes],
    )
    async_db.add(plan)
    await async_db.flush()
    await replace_compiled_rules(
        async_db, user_id=user.id, plan=plan, nodes=nodes, ordering_mode="strict_sequential"
    )
    await refresh_user_blocked_status(user.id, async_db)
    assert target.thread_id not in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    reasons = await get_blocking_explanations(target.thread_id, user.id, async_db)
    assert [reason.label for reason in reasons] == ["Blocked by Starman: #55"]
    snapshot = await load_snapshot(async_db, user.id)
    assert [blocker.source_id for blocker in issue_readiness(target.id, snapshot)] == [source.id]
    source.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    assert target.thread_id in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    assert await get_blocking_explanations(target.thread_id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_same_thread_strict_order_needs_no_materialized_adjacency(
    async_db: AsyncSession,
) -> None:
    """Natural Thread order stays sufficient even when displayed in a strict plan."""
    user = await get_or_create_user_async(async_db)
    first = await make_issue(async_db, user.id, "Cable", "63")
    second = Issue(thread_id=first.thread_id, issue_number="64", position=2, status="unread")
    async_db.add(second)
    await async_db.flush()
    nodes = [node(first, 0), node(second, 1)]
    plan = ContinuityPlan(
        user_id=user.id,
        name="Natural lane",
        ordering_mode="strict_sequential",
        lanes_json=[],
        nodes_json=[item.model_dump() for item in nodes],
    )
    async_db.add(plan)
    await async_db.flush()
    await replace_compiled_rules(
        async_db, user_id=user.id, plan=plan, nodes=nodes, ordering_mode="strict_sequential"
    )
    assert list((await async_db.scalars(select(Dependency))).all()) == []
    first.status = "read"
    thread = await async_db.get(Thread, first.thread_id)
    assert thread is not None
    thread.next_unread_issue_id = second.id
    await refresh_user_blocked_status(user.id, async_db)
    assert await get_blocking_explanations(thread.id, user.id, async_db) == []


@pytest.mark.asyncio
async def test_historical_mirror_does_not_promote_cbl_order(async_db: AsyncSession) -> None:
    """Compatibility mirroring is not independent evidence of reader hard intent."""
    user = await get_or_create_user_async(async_db)
    source = await make_issue(async_db, user.id, "Template source", "1")
    target = await make_issue(async_db, user.id, "Template target", "1")
    dep = Dependency(
        source_issue_id=source.id, target_issue_id=target.id, note="cbl-order:group-16:1->2"
    )
    async_db.add(dep)
    await async_db.flush()
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=source.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="item_read",
            legacy_dependency_id=dep.id,
            note=dep.note,
        )
    )
    await synchronize_canonical_constraints(async_db, user.id)
    await refresh_user_blocked_status(user.id, async_db)
    assert dep.note == "cbl-order:group-16:1->2"
    assert target.thread_id in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    assert await get_blocking_explanations(target.thread_id, user.id, async_db) == []


def load_cutover_migration() -> ModuleType:
    """Load the deployment migration for executable SQL regression coverage."""
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/f25530000001_canonical_roll_constraints.py"
    )
    spec = importlib.util.spec_from_file_location("canonical_cutover_migration_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_deployment_backfill_expands_convergence_and_preserves_reader_frontiers(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The actual deployment SQL inserts incoming gates before flags switch."""
    user = await get_or_create_user_async(async_db)
    first = await make_issue(async_db, user.id, "X-Men", "95")
    second = await make_issue(async_db, user.id, "X-Force", "1")
    target = await make_issue(async_db, user.id, "Cable", "75")
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=target.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="converged",
            convergence_targets=[
                {"type": "issue", "id": first.id},
                {"type": "issue", "id": second.id},
            ],
        )
    )
    await async_db.flush()
    module = load_cutover_migration()
    statements: list[Executable] = []
    monkeypatch.setattr(module.op, "execute", statements.append)
    module.upgrade()
    for statement in statements:
        await async_db.execute(statement)
    edges = list((await async_db.scalars(select(Dependency))).all())
    assert {(edge.source_issue_id, edge.target_issue_id) for edge in edges} == {
        (first.id, target.id),
        (second.id, target.id),
    }
    target_thread = await async_db.get(Thread, target.thread_id)
    assert target_thread is not None
    await async_db.refresh(target_thread)
    assert target.thread_id not in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    first.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    assert target.thread_id not in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    second.status = "read"
    await refresh_user_blocked_status(user.id, async_db)
    assert target.thread_id in {thread.id for thread in await get_roll_pool(user.id, async_db)}


@pytest.mark.asyncio
async def test_compilation_rejects_cycle_with_unmirrored_standalone_dependency(
    async_db: AsyncSession,
) -> None:
    """Canonical standalone edges still participate after the bridge is retired."""
    user = await get_or_create_user_async(async_db)
    first = await make_issue(async_db, user.id, "First", "1")
    second = await make_issue(async_db, user.id, "Second", "1")
    async_db.add(Dependency(source_issue_id=first.id, target_issue_id=second.id))
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=second.id,
            target_type="issue",
            target_id=first.id,
            satisfaction_type="item_read",
        )
    )
    with pytest.raises(HTTPException) as error:
        await synchronize_canonical_constraints(async_db, user.id)
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "continuity_cycle"}
    deps = list((await async_db.scalars(select(Dependency))).all())
    assert [(dep.source_issue_id, dep.target_issue_id) for dep in deps] == [(first.id, second.id)]


@pytest.mark.asyncio
async def test_inert_historical_mirror_does_not_reject_explicit_opposite_hard_intent(
    async_db: AsyncSession,
) -> None:
    """Historical source ordering cannot veto a reader's explicit hard plan."""
    user = await get_or_create_user_async(async_db)
    first = await make_issue(async_db, user.id, "Historical first", "1")
    second = await make_issue(async_db, user.id, "Reader prerequisite", "1")
    async_db.add(
        Dependency(
            source_issue_id=first.id,
            target_issue_id=second.id,
            note="cbl-order:source",
        )
    )
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=first.id,
            target_type="issue",
            target_id=second.id,
            satisfaction_type="item_read",
            note="cbl-order:source",
        )
    )
    nodes = [node(second, 0), node(first, 1)]
    plan = ContinuityPlan(
        user_id=user.id,
        name="Explicit reader intent",
        ordering_mode="strict_sequential",
        lanes_json=[],
        nodes_json=[item.model_dump() for item in nodes],
    )
    async_db.add(plan)
    await async_db.flush()
    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await refresh_user_blocked_status(user.id, async_db)
    assert first.thread_id not in {thread.id for thread in await get_roll_pool(user.id, async_db)}
    assert second.thread_id in {thread.id for thread in await get_roll_pool(user.id, async_db)}
