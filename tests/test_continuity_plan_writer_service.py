"""Focused service coverage for the shared Reading Plan writer and strict-rule compiler.

Issue #2379: node-ownership validation and compiled-rule replacement must live
in one reusable service so normal plan saves and CBL adoption compile rules
identically. These tests prove the extracted service preserves the router's
informational / strict-sequential / checkpoint / convergence semantics and its
cycle and conflict error codes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import continuity_plan as continuity_plan_api
from app.continuity_plan_readiness import plan_rule_marker
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode, ConvergenceGateTarget, PlanOrderingMode
from app.services.continuity_plan_writer import (
    replace_compiled_rules,
    validate_node_ownership,
)
from tests.conftest import get_or_create_user_async


class PlanNodeDict(TypedDict):
    """TypedDict for a plan node in router API payloads."""

    id: str
    node_type: str
    ref_id: int
    lane_id: str
    position: int
    is_checkpoint: bool | None
    convergence_gate: list[dict[str, str]] | None


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned issue for continuity-plan tests."""
    thread = Thread(
        title=f"Writer {suffix}",
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
    return issue


def _nodes(issue_ids: list[int], *, lane_id: str = "main") -> list[ContinuityPlanNode]:
    """Build one-lane canonical node models for the shared writer."""
    return [
        ContinuityPlanNode(
            id=f"issue-{issue_id}",
            node_type="issue",
            ref_id=issue_id,
            lane_id=lane_id,
            position=position,
            is_checkpoint=False,
            convergence_gate=[],
        )
        for position, issue_id in enumerate(issue_ids)
    ]


def _router_payload(issue_ids: list[int], *, mode: str = "informational") -> dict[str, object]:
    """Build a router-shaped one-lane plan payload."""
    nodes: list[PlanNodeDict] = []
    for position, issue_id in enumerate(issue_ids):
        nodes.append({
            "id": f"issue-{issue_id}",
            "node_type": "issue",
            "ref_id": issue_id,
            "lane_id": "main",
            "position": position,
            "is_checkpoint": False,
            "convergence_gate": None,
        })
    return {
        "name": "Writer plan",
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": nodes,
    }


async def _user_rules(db: AsyncSession, *, user_id: int) -> list[ContinuityRule]:
    """Return every persisted rule for one user in stable order."""
    rows = (
        await db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user_id)
            .order_by(ContinuityRule.source_id, ContinuityRule.target_id)
        )
    ).scalars().all()
    return rows


async def _write_plan_via_service(
    db: AsyncSession,
    *,
    user_id: int,
    nodes: list[ContinuityPlanNode],
    ordering_mode: PlanOrderingMode,
) -> ContinuityPlan:
    """Write one plan through the shared service, exactly as the router would."""
    await validate_node_ownership(db, user_id=user_id, nodes=nodes)
    plan = ContinuityPlan(
        user_id=user_id,
        name="Service strict",
        ordering_mode=ordering_mode,
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()
    await replace_compiled_rules(
        db,
        user_id=user_id,
        plan=plan,
        nodes=nodes,
        ordering_mode=ordering_mode,
    )
    await db.commit()
    await db.refresh(plan)
    return plan


async def _clear_plan_rules(db: AsyncSession, *, user_id: int, plan_id: int) -> None:
    """Remove the compiled rules owned by one plan so a peer writer can reuse the edges.

    Two plans may not both own the same hard edge — that is the preserved
    ``plan_rule_conflict`` contract — so a comparison test that compiles the
    same strict edges through two writers must clear the first writer's rules
    before the second writer runs.
    """
    await db.execute(
        delete(ContinuityRule).where(
            ContinuityRule.user_id == user_id,
            ContinuityRule.note == plan_rule_marker(plan_id),
        ),
        execution_options={"synchronize_session": "fetch"},
    )
    await db.commit()


@pytest.mark.asyncio
async def test_strict_sequential_adjacent_rules_compile_identically_to_router(
    async_db: AsyncSession,
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shared compiler and the router compile the exact same strict rules."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()

    service_plan = await _write_plan_via_service(
        async_db,
        user_id=user.id,
        nodes=_nodes([issue.id for issue in issues]),
        ordering_mode="strict_sequential",
    )
    service_rules = [
        rule
        for rule in await _user_rules(async_db, user_id=user.id)
        if rule.note == f"continuity-plan:{service_plan.id}"
    ]
    service_rule_edges = [
        (rule.source_id, rule.target_id, rule.satisfaction_type) for rule in service_rules
    ]
    assert service_rule_edges == [
        (issues[0].id, issues[1].id, "item_read"),
        (issues[1].id, issues[2].id, "item_read"),
    ]
    assert all(rule.note == f"continuity-plan:{service_plan.id}" for rule in service_rules)

    # The service compile is proven above; clear its plan-owned rules so the
    # router can compile the exact same edges without a plan_rule_conflict.
    await _clear_plan_rules(async_db, user_id=user.id, plan_id=service_plan.id)

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_router_payload([issue.id for issue in issues], mode="strict_sequential"),
    )
    assert created.status_code == 201, created.text
    router_plan_id = created.json()["id"]
    router_rules = [
        rule
        for rule in await _user_rules(async_db, user_id=user.id)
        if rule.note == f"continuity-plan:{router_plan_id}"
    ]

    assert [
        (r.source_id, r.target_id, r.satisfaction_type) for r in router_rules
    ] == service_rule_edges
    assert all(r.note == f"continuity-plan:{router_plan_id}" for r in router_rules)


@pytest.mark.asyncio
async def test_informational_compile_creates_zero_strict_rules(
    async_db: AsyncSession,
) -> None:
    """Updating/saving an informational plan continues to create no hard order rules."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()

    await _write_plan_via_service(
        async_db,
        user_id=user.id,
        nodes=_nodes([issue.id for issue in issues]),
        ordering_mode="informational",
    )

    assert await _user_rules(async_db, user_id=user.id) == []


@pytest.mark.asyncio
async def test_validate_node_ownership_rejects_unowned_reference(
    async_db: AsyncSession,
) -> None:
    """Extracted ownership validation keeps the dangling-reference contract."""
    user = await get_or_create_user_async(async_db)
    with pytest.raises(HTTPException) as captured:
        await validate_node_ownership(
            async_db,
            user_id=user.id,
            nodes=_nodes([987654321]),
        )
    assert captured.value.status_code == 422
    assert captured.value.detail == {"code": "dangling_plan_reference", "node_id": "issue-987654321"}


@pytest.mark.asyncio
async def test_checkpoint_rule_compiles_through_shared_writer(
    async_db: AsyncSession,
) -> None:
    """Checkpoint semantics survive extraction exactly."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    nodes = _nodes([issue.id for issue in issues])
    nodes[1] = ContinuityPlanNode(
        id=nodes[1].id,
        node_type=nodes[1].node_type,
        ref_id=nodes[1].ref_id,
        lane_id=nodes[1].lane_id,
        position=nodes[1].position,
        is_checkpoint=True,
        convergence_gate=[],
    )
    plan = await _write_plan_via_service(
        async_db,
        user_id=user.id,
        nodes=nodes,
        ordering_mode="informational",
    )

    rules = await _user_rules(async_db, user_id=user.id)
    checkpoint_rules = [rule for rule in rules if rule.satisfaction_type == "checkpoint"]
    assert len(checkpoint_rules) == 1
    rule = checkpoint_rules[0]
    assert rule.source_id == issues[1].id
    assert rule.target_id == issues[2].id
    assert rule.checkpoint_issue_id == issues[1].id
    assert rule.note == f"continuity-plan:{plan.id}"


@pytest.mark.asyncio
async def test_convergence_gate_rule_compiles_through_shared_writer(
    async_db: AsyncSession,
) -> None:
    """Convergence gates compile the same converged self-loop through the service."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()

    nodes = _nodes([issue.id for issue in lane_a], lane_id="era-a") + _nodes(
        [issue.id for issue in lane_b],
        lane_id="era-b",
    )
    gate_target = next(node for node in nodes if node.id == f"issue-{lane_a[1].id}")
    b_first = next(node for node in nodes if node.id == f"issue-{lane_b[0].id}")
    gated = [
        node if node.id != b_first.id else b_first.model_copy(
            update={"convergence_gate": [
                ConvergenceGateTarget(
                    node_type=gate_target.node_type,
                    node_id=gate_target.id,
                )
            ]}
        )
        for node in nodes
    ]
    await _write_plan_via_service(
        async_db,
        user_id=user.id,
        nodes=gated,
        ordering_mode="informational",
    )

    rules = await _user_rules(async_db, user_id=user.id)
    converged = [rule for rule in rules if rule.satisfaction_type == "converged"]
    assert len(converged) == 1
    rule = converged[0]
    assert rule.source_id == lane_b[0].id
    assert rule.target_id == lane_b[0].id
    assert rule.convergence_targets == [{"type": "issue", "id": lane_a[1].id}]


@pytest.mark.asyncio
async def test_convergence_cycle_error_keeps_stable_code(
    async_db: AsyncSession,
) -> None:
    """The shared compiler preserves the plan-level cycle conflict contract."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    first, second = _nodes([issue.id for issue in issues])
    cyclic = [
        first.model_copy(update={"convergence_gate": [
            ConvergenceGateTarget(
                node_type=second.node_type,
                node_id=second.id,
            )
        ]}),
        second.model_copy(update={"convergence_gate": [
            ConvergenceGateTarget(
                node_type=first.node_type,
                node_id=first.id,
            )
        ]}),
    ]
    plan = ContinuityPlan(
        user_id=user.id,
        name="Cycle",
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[node.model_dump() for node in cyclic],
    )
    async_db.add(plan)
    await async_db.flush()
    await validate_node_ownership(async_db, user_id=user.id, nodes=cyclic)
    with pytest.raises(HTTPException) as captured:
        await replace_compiled_rules(
            async_db,
            user_id=user.id,
            plan=plan,
            nodes=cyclic,
            ordering_mode="informational",
        )
    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "plan_convergence_cycle"