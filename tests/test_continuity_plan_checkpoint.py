"""API coverage for plan-level checkpoint and convergence-gate compilation."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import continuity_plan as continuity_plan_api
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import _has_cycle
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned issue for continuity-plan checkpoint tests."""
    thread = Thread(
        title=f"Plan {suffix}",
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


def _plan_payload(
    issue_ids: list[int],
    *,
    checkpoints: list[str] | None = None,
    convergence_gates: list[dict[str, object]] | None = None,
    mode: str = "informational",
) -> dict[str, object]:
    """Build a one-lane plan payload with optional checkpoint/gate semantics."""
    return {
        "name": "Checkpoint plan",
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": f"issue-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "main",
                "position": position,
            }
            for position, issue_id in enumerate(issue_ids)
        ],
        "checkpoints": [{"node_id": node_id} for node_id in (checkpoints or [])],
        "convergence_gates": convergence_gates or [],
    }


@pytest.mark.asyncio
async def test_checkpoint_compiles_idempotent_rules(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint compiles one checkpoint rule per later same-lane node, repeatably."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload(
        [issue.id for issue in issues],
        checkpoints=[f"issue-{issues[0].id}"],
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert created.json()["checkpoints"] == [{"node_id": f"issue-{issues[0].id}"}]

    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user.id)
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    assert len(rules) == 2
    assert all(rule.satisfaction_type == "checkpoint" for rule in rules)
    assert all(rule.checkpoint_issue_id == issues[0].id for rule in rules)
    assert all(rule.note == f"continuity-plan:{plan_id}" for rule in rules)
    later = {rule.target_id for rule in rules}
    assert later == {issues[1].id, issues[2].id}

    repeated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert repeated.status_code == 200, repeated.text
    repeated_rules = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert len(repeated_rules) == 2


@pytest.mark.asyncio
async def test_convergence_gate_compiles_converged_rule(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A convergence gate compiles one converged rule waiting on the selected nodes."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload(
        [issue.id for issue in issues],
        convergence_gates=[
            {
                "id": "gate-1",
                "gate_node_id": f"issue-{issues[2].id}",
                "wait_for": [
                    {"node_id": f"issue-{issues[0].id}"},
                    {"node_id": f"issue-{issues[1].id}"},
                ],
            }
        ],
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rule = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.satisfaction_type == "converged",
            )
        )
    ).scalar_one()
    assert rule.target_id == issues[2].id
    assert rule.note == f"continuity-plan:{plan_id}"
    targets = {(target["type"], target["id"]) for target in (rule.convergence_targets or [])}
    assert targets == {("issue", issues[0].id), ("issue", issues[1].id)}


@pytest.mark.asyncio
async def test_remove_gate_removes_only_plan_owned_rules(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dropping a gate deletes only the rules that gate compiled."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload(
        [issue.id for issue in issues],
        convergence_gates=[
            {
                "id": "gate-1",
                "gate_node_id": f"issue-{issues[2].id}",
                "wait_for": [{"node_id": f"issue-{issues[0].id}"}],
            }
        ],
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    updated = dict(payload)
    updated["convergence_gates"] = []
    response = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=updated)
    assert response.status_code == 200, response.text
    assert response.json()["convergence_gates"] == []

    remaining = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_checkpoint_on_crossover_rejected_before_write(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Checkpoints must pin an issue node; a crossover checkpoint is rejected."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="x")
    await async_db.commit()
    payload = {
        "name": "Bad checkpoint",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "issue-1", "node_type": "issue", "ref_id": issue.id, "lane_id": "main", "position": 0}
        ],
        "convergence_gates": [],
        "checkpoints": [{"node_id": "issue-1"}],
    }
    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "checkpoint_invalid_node"
    plans = (await async_db.execute(select(ContinuityPlan))).scalars().all()
    assert plans == []


@pytest.mark.asyncio
async def test_convergence_self_wait_rejected_before_write(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate cannot wait for its own gate node."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="x")
    await async_db.commit()
    payload = {
        "name": "Self gate",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {"id": "issue-1", "node_type": "issue", "ref_id": issue.id, "lane_id": "main", "position": 0}
        ],
        "checkpoints": [],
        "convergence_gates": [
            {"id": "g1", "gate_node_id": "issue-1", "wait_for": [{"node_id": "issue-1"}]}
        ],
    }
    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "convergence_self_wait"


@pytest.mark.asyncio
async def test_plan_gate_cycle_rejected_before_write(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate that waits on its own downstream target is cyclic."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = _plan_payload(
        [issue.id for issue in issues],
        convergence_gates=[
            {
                "id": "g1",
                "gate_node_id": f"issue-{issues[0].id}",
                "wait_for": [{"node_id": f"issue-{issues[1].id}"}],
            }
        ],
    )
    # issues[1] -> gate blocks issues[0] until issues[1]; also make issues[1] wait on
    # issues[0] via a checkpoint, producing a cycle in the plan graph.
    payload["checkpoints"] = [{"node_id": f"issue-{issues[1].id}"}]
    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code in {422, 409}
    assert response.json()["detail"]["code"] in {"plan_gate_cycle", "continuity_cycle"}


@pytest.mark.asyncio
async def test_checkpoint_blocks_later_readiness(
    auth_client: AsyncClient, async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Readiness reports a checkpoint-blocked later node with a human-readable code."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = _plan_payload(
        [issue.id for issue in issues],
        checkpoints=[f"issue-{issues[0].id}"],
    )
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    readiness = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert readiness.status_code == 200, readiness.text
    body = readiness.json()
    later = next(node for node in body["nodes"] if node["ref_id"] == issues[1].id)
    assert later["is_readable"] is False
    assert any(
        diagnostic["code"] == "checkpoint_blocking" for diagnostic in later["diagnostics"]
    )


def test_has_cycle_detects_plan_local_cycle() -> None:
    """The shared cycle detector flags a directed cycle across plan edges."""
    nodes = {"a", "b", "c"}
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    assert _has_cycle(nodes, edges) is True
    assert _has_cycle(nodes, [("a", "b"), ("b", "c")]) is False
