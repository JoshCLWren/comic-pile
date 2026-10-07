"""Coverage for the one-membership-per-canonical-issue invariant (#3037)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.continuity_plan import ContinuityPlan
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.thread import Thread
from app.models.user import User
from app.schemas.continuity_plan import ContinuityPlanLane, ContinuityPlanNode, ContinuityPlanWrite
from app.services.reading_plan_normalization import (
    ensure_plan_issue_uniqueness,
    rebuild_plan_membership,
)
from tests.conftest import get_or_create_user_async, get_test_database_url


def _lane() -> ContinuityPlanLane:
    return ContinuityPlanLane(id="main", name="Main", order=0)


def _node(node_id: str, ref_id: int, position: int, node_type: str = "issue") -> ContinuityPlanNode:
    return ContinuityPlanNode(
        id=node_id,
        node_type=node_type,  # type: ignore[arg-type]
        ref_id=ref_id,
        lane_id="main",
        position=position,
    )


async def _make_issue(db: AsyncSession, *, user_id: int, title: str) -> Issue:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    return issue


async def _make_plan(
    db: AsyncSession, *, user_id: int, nodes: list[ContinuityPlanNode], name: str = "Plan"
) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="informational",
        lanes_json=[_lane().model_dump()],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()
    return plan


def test_schema_rejects_duplicate_issue_refs() -> None:
    """ContinuityPlanWrite fails closed on repeated canonical issues."""
    with pytest.raises(ValueError, match="at most once"):
        ContinuityPlanWrite(
            name="Dup",
            ordering_mode="informational",
            lanes=[_lane()],
            nodes=[_node("a", 1, 0), _node("b", 1, 1)],
        )
    # Distinct issues are fine; repeated non-issue refs are not membership.
    ContinuityPlanWrite(
        name="Ok",
        ordering_mode="informational",
        lanes=[_lane()],
        nodes=[_node("a", 1, 0), _node("b", 2, 1), _node("c", 1, 2, node_type="thread")],
    )


def test_service_gate_rejects_duplicate_issue_nodes() -> None:
    """The service gate names the repeated issue with a domain error code."""
    with pytest.raises(HTTPException) as exc_info:
        ensure_plan_issue_uniqueness([_node("a", 7, 0), _node("b", 7, 1)])
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "duplicate_plan_issue"
    assert exc_info.value.detail["issue_id"] == 7
    ensure_plan_issue_uniqueness([_node("a", 7, 0), _node("b", 8, 1)])


@pytest.mark.asyncio
async def test_rebuild_fails_closed_without_writing_rows(async_db: AsyncSession) -> None:
    """rebuild_plan_membership rejects duplicates before replacing any rows."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="A")
    plan = await _make_plan(
        async_db, user_id=user.id, nodes=[_node("a", issue.id, 0), _node("b", issue.id, 1)]
    )
    with pytest.raises(HTTPException, match="duplicate_plan_issue"):
        await rebuild_plan_membership(
            async_db, plan_id=plan.id, nodes=[_node("a", issue.id, 0), _node("b", issue.id, 1)]
        )
    count = await async_db.scalar(
        select(func.count()).select_from(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan.id)
    )
    assert count == 0


@pytest.mark.asyncio
async def test_db_constraint_rejects_second_occurrence(async_db: AsyncSession) -> None:
    """uq_reading_plan_issue_once_per_plan is the database backstop."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, title="A")
    plan = await _make_plan(async_db, user_id=user.id, nodes=[_node("a", issue.id, 0)])
    async_db.add(
        ReadingPlanIssue(
            plan_id=plan.id, occurrence_id="a", issue_id=issue.id, lane_id="main", display_position=0
        )
    )
    await async_db.flush()
    async_db.add(
        ReadingPlanIssue(
            plan_id=plan.id, occurrence_id="b", issue_id=issue.id, lane_id="main", display_position=1
        )
    )
    with pytest.raises(IntegrityError, match="uq_reading_plan_issue_once_per_plan"):
        await async_db.flush()


@pytest.mark.asyncio
async def test_api_create_rejects_duplicate_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """POST /continuity-plans/ with a repeated issue returns 422."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, title="A")
    issue_b = await _make_issue(async_db, user_id=user.id, title="B")
    await async_db.commit()
    payload = {
        "name": "Dup plan",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "n1", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 0},
            {"id": "n2", "node_type": "issue", "ref_id": issue_b.id, "lane_id": "main", "position": 1},
            {"id": "n3", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 2},
        ],
    }
    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_api_update_rejects_duplicate_issue(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """PUT /continuity-plans/{id} with a repeated issue returns 422."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, title="A")
    issue_b = await _make_issue(async_db, user_id=user.id, title="B")
    await async_db.commit()
    payload = {
        "name": "Clean plan",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "n1", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 0},
            {"id": "n2", "node_type": "issue", "ref_id": issue_b.id, "lane_id": "main", "position": 1},
        ],
    }
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    payload["nodes"].append(
        {"id": "n3", "node_type": "issue", "ref_id": issue_a.id, "lane_id": "main", "position": 2}
    )
    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert updated.status_code == 422, updated.text


@pytest.mark.asyncio
async def test_audit_and_reconcile_duplicates(async_db: AsyncSession) -> None:
    """The audit script finds duplicates; reconcile collapses exact ones only."""
    import scripts.audit_reading_plan_issue_duplicates as audit_mod

    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, title="A")
    issue_b = await _make_issue(async_db, user_id=user.id, title="B")

    def node_dict(node_id: str, ref_id: int, position: int, **extra) -> dict:
        base = _node(node_id, ref_id, position).model_dump()
        base.update(extra)
        return base

    # Plan 1: exact-duplicate occurrences -> deterministically collapsible.
    plan1 = ContinuityPlan(
        user_id=user.id,
        name="Exact dups",
        ordering_mode="informational",
        lanes_json=[_lane().model_dump()],
        nodes_json=[
            node_dict("a1", issue_a.id, 0),
            node_dict("b1", issue_b.id, 1),
            node_dict("a2", issue_a.id, 2),
        ],
    )
    # Plan 2: conflicting duplicates (different labels) -> blocker, untouched.
    plan2 = ContinuityPlan(
        user_id=user.id,
        name="Conflicting dups",
        ordering_mode="informational",
        lanes_json=[_lane().model_dump()],
        nodes_json=[
            node_dict("a1", issue_a.id, 0, label="first"),
            node_dict("a2", issue_a.id, 1, label="second"),
        ],
    )
    async_db.add_all([plan1, plan2])
    await async_db.flush()

    report = await audit_mod.audit(async_db)
    assert {p["plan_id"] for p in report["plans_with_duplicate_nodes"]} == {plan1.id, plan2.id}

    result = await audit_mod.reconcile(async_db)
    assert result["plans_fixed"] == 1
    assert result["collapsed"][0]["kept_node_id"] == "a1"
    assert result["collapsed"][0]["dropped_node_ids"] == ["a2"]
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["plan_id"] == plan2.id

    await async_db.refresh(plan1)
    ref_ids = [n["ref_id"] for n in plan1.nodes_json if n["node_type"] == "issue"]
    assert ref_ids == [issue_a.id, issue_b.id]
    assert [n["position"] for n in plan1.nodes_json] == [0, 1]
    # Normalized membership matches the deduped nodes.
    rows = (
        await async_db.execute(
            select(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan1.id)
        )
    ).scalars().all()
    assert sorted(row.issue_id for row in rows) == sorted([issue_a.id, issue_b.id])
    # Conflicting plan untouched.
    await async_db.refresh(plan2)
    assert len(plan2.nodes_json) == 2


@pytest.mark.asyncio
async def test_concurrent_duplicate_inserts_converge() -> None:
    """Two concurrent writers racing the same membership converge via the constraint.

    NOTE: this test deliberately avoids the function-scoped ``async_db``
    fixture. The fixture holds its transaction (and TRUNCATE locks) open for
    the whole test, which would block the racers' foreign-key checks forever.
    All connections here commit promptly and clean up after themselves.
    """
    import uuid

    from sqlalchemy import delete

    url = get_test_database_url()

    async def fresh_session():
        engine = create_async_engine(url, poolclass=NullPool)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        return engine, maker()

    setup_engine, setup = await fresh_session()
    try:
        username = f"raceuser_{uuid.uuid4().hex[:8]}"
        user = User(username=username, email=f"{username}@example.com", password_hash="x")
        setup.add(user)
        await setup.flush()
        issue = await _make_issue(setup, user_id=user.id, title="Race")
        plan = await _make_plan(setup, user_id=user.id, nodes=[])
        await setup.commit()
        plan_id, issue_id, thread_id, user_id = plan.id, issue.id, issue.thread_id, user.id
    finally:
        await setup.close()
        await setup_engine.dispose()

    async def attempt() -> bool:
        engine, session = await fresh_session()
        try:
            session.add(
                ReadingPlanIssue(
                    plan_id=plan_id,
                    occurrence_id=f"occ-{uuid.uuid4().hex[:8]}",
                    issue_id=issue_id,
                    lane_id="main",
                    display_position=0,
                )
            )
            await session.commit()
            return True
        except IntegrityError:
            await session.rollback()
            return False
        finally:
            await session.close()
            await engine.dispose()

    check_engine, check = await fresh_session()
    try:
        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == [False, True]

        count = await check.scalar(
            select(func.count())
            .select_from(ReadingPlanIssue)
            .where(
                ReadingPlanIssue.plan_id == plan_id,
                ReadingPlanIssue.issue_id == issue_id,
            )
        )
        assert count == 1
    finally:
        await check.execute(
            delete(ReadingPlanIssue).where(ReadingPlanIssue.plan_id == plan_id)
        )
        await check.execute(delete(ContinuityPlan).where(ContinuityPlan.id == plan_id))
        await check.execute(delete(Issue).where(Issue.id == issue_id))
        await check.execute(delete(Thread).where(Thread.id == thread_id))
        await check.execute(delete(User).where(User.id == user_id))
        await check.commit()
        await check.close()
        await check_engine.dispose()
