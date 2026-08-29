"""API coverage for persisted continuity plans and explicit rule compilation."""

from datetime import UTC, datetime
from typing import TypedDict
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
from tests.conftest import get_or_create_user_async


class PlanNodeDict(TypedDict):
    """TypedDict for a plan node in test payloads."""

    id: str
    node_type: str
    ref_id: int
    lane_id: str
    position: int
    is_checkpoint: bool | None
    convergence_gate: list[dict[str, str]] | None


class PlanPayloadDict(TypedDict):
    """TypedDict for a complete plan payload in tests."""

    name: str
    ordering_mode: str
    lanes: list[dict[str, str | int]]
    nodes: list[PlanNodeDict]


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned issue for continuity-plan tests."""
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


def _plan_payload(issue_ids: list[int], *, mode: str = "informational") -> PlanPayloadDict:
    """Build a one-lane plan payload."""
    return {
        "name": "Imported crossover",
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": f"issue-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "main",
                "position": position,
                "is_checkpoint": False,
                "convergence_gate": None,
            }
            for position, issue_id in enumerate(issue_ids)
        ],
    }


@pytest.mark.asyncio
async def test_informational_plan_round_trips_without_creating_rules(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A long imported order remains purely informational by default."""
    user = await get_or_create_user_async(async_db)
    issues = [
        await _make_issue(async_db, user_id=user.id, suffix=str(index)) for index in range(12)
    ]
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload([issue.id for issue in issues]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["ordering_mode"] == "informational"
    assert [node["ref_id"] for node in body["nodes"]] == [issue.id for issue in issues]

    rules = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert rules == []

    fetched = await auth_client.get(f"/api/v1/continuity-plans/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["nodes"] == body["nodes"]


@pytest.mark.asyncio
async def test_strict_plan_compiles_idempotently_then_informational_update_removes_owned_rules(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit strict intent creates adjacent edges; reverting intent removes only plan-owned edges."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues], mode="strict_sequential")

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user.id)
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    assert [(rule.source_id, rule.target_id) for rule in rules] == [
        (issues[0].id, issues[1].id),
        (issues[1].id, issues[2].id),
    ]
    assert all(rule.note == f"continuity-plan:{plan_id}" for rule in rules)

    repeated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert repeated.status_code == 200, repeated.text
    count_after_repeat = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.user_id == user.id)
        )
    ).scalars().all()
    assert len(count_after_repeat) == 2

    informational = dict(payload)
    informational["ordering_mode"] = "informational"
    updated = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}", json=informational
    )
    assert updated.status_code == 200, updated.text
    remaining = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert remaining == []


@pytest.mark.asyncio
async def test_dangling_reference_rejects_plan_before_write(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Invalid references return an editor-friendly error without partial persistence."""
    payload = _plan_payload([987654321])
    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "dangling_plan_reference"
    plans = (await async_db.execute(select(ContinuityPlan))).scalars().all()
    assert plans == []


def test_strict_plan_rejects_parallel_lanes_and_thread_nodes() -> None:
    """Strict compilation is opt-in and limited to the simple linear shape."""
    parallel = {
        "name": "Parallel",
        "ordering_mode": "strict_sequential",
        "lanes": [
            {"id": "a", "name": "A", "order": 0},
            {"id": "b", "name": "B", "order": 1},
        ],
        "nodes": [],
    }
    response_shape = continuity_plan_api.ContinuityPlanWrite
    with pytest.raises(ValueError, match="exactly one lane"):
        response_shape.model_validate(parallel)

    thread_payload = {
        "name": "Thread",
        "ordering_mode": "strict_sequential",
        "lanes": [{"id": "a", "name": "A", "order": 0}],
        "nodes": [
            {"id": "t", "node_type": "thread", "ref_id": 1, "lane_id": "a", "position": 0}
        ],
    }
    with pytest.raises(ValueError, match="issue/crossover"):
        response_shape.model_validate(thread_payload)


def _parallel_payload(
    lane_a: list[int], lane_b: list[int]
) -> PlanPayloadDict:
    """Build a two-lane informational plan payload with one issue node per entry."""
    nodes: list[PlanNodeDict] = []
    for position, issue_id in enumerate(lane_a):
        nodes.append(
            {
                "id": f"a-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "era-a",
                "position": position,
                "is_checkpoint": False,
                "convergence_gate": None,
            }
        )
    for position, issue_id in enumerate(lane_b):
        nodes.append(
            {
                "id": f"b-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "era-b",
                "position": position,
                "is_checkpoint": False,
                "convergence_gate": None,
            }
        )
    return {
        "name": "Parallel",
        "ordering_mode": "informational",
        "lanes": [
            {"id": "era-a", "name": "Era A", "order": 0},
            {"id": "era-b", "name": "Era B", "order": 1},
        ],
        "nodes": nodes,
    }


@pytest.mark.asyncio
async def test_parallel_lanes_survive_save_and_reload(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Two parallel lanes and their members round-trip unchanged."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    payload = _parallel_payload([issue.id for issue in lane_a], [issue.id for issue in lane_b])

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    assert [lane["id"] for lane in body["lanes"]] == ["era-a", "era-b"]
    assert {(node["lane_id"], node["position"]) for node in body["nodes"]} == {
        ("era-a", 0),
        ("era-a", 1),
        ("era-b", 0),
        ("era-b", 1),
    }

    fetched = await auth_client.get(f"/api/v1/continuity-plans/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["lanes"] == body["lanes"]
    assert fetched.json()["nodes"] == body["nodes"]


@pytest.mark.asyncio
async def test_parallel_lanes_invent_no_blocking_edges(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Separate lanes compile no cross-lane rules, so members stay simultaneously eligible."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 5)]
    await async_db.commit()
    payload = _parallel_payload([issue.id for issue in lane_a], [issue.id for issue in lane_b])

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text

    rules = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert rules == []


@pytest.mark.asyncio
async def test_moving_node_between_lanes_updates_only_intended_state(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Relocating a node changes only its lane placement, never its underlying comic data."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    moved = lane_a[1]
    payload = _parallel_payload([issue.id for issue in lane_a], [issue.id for issue in lane_b])

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    lanes = [lane["id"] for lane in created.json()["lanes"]]
    moved_id = f"a-{moved.id}"
    nodes = [node for node in created.json()["nodes"] if node["id"] != moved_id]
    nodes.append(
        {
            "id": moved_id,
            "node_type": "issue",
            "ref_id": moved.id,
            "lane_id": "era-b",
            "position": 2,
        }
    )
    moved_payload = {"name": "Parallel", "ordering_mode": "informational", "lanes": [
        {"id": "era-a", "name": "Era A", "order": 0},
        {"id": "era-b", "name": "Era B", "order": 1},
    ], "nodes": nodes}

    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=moved_payload)
    assert updated.status_code == 200, updated.text
    persisted = (await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.id == plan_id))).scalar_one()
    node_by_id = {node["id"]: node for node in persisted.nodes_json}
    assert node_by_id[moved_id]["lane_id"] == "era-b"
    assert node_by_id[moved_id]["ref_id"] == moved.id
    assert node_by_id[moved_id]["node_type"] == "issue"
    assert {node["id"] for node in node_by_id.values()} == {node["id"] for node in nodes}
    assert lanes == ["era-a", "era-b"]
    rules = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert rules == []


@pytest.mark.asyncio
async def test_empty_lane_persists_and_can_become_empty(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Empty lanes survive save/reload and are not dropped when their last member moves out."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(1)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(1, 3)]
    await async_db.commit()
    payload = _parallel_payload([issue.id for issue in lane_a], [issue.id for issue in lane_b])

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    vacate = _parallel_payload([], [issue.id for issue in lane_b])
    vacated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=vacate)
    assert vacated.status_code == 200, vacated.text
    assert [lane["id"] for lane in vacated.json()["lanes"]] == ["era-a", "era-b"]
    assert [node["lane_id"] for node in vacated.json()["nodes"]] == ["era-b", "era-b"]

    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert fetched.status_code == 200
    assert [lane["id"] for lane in fetched.json()["lanes"]] == ["era-a", "era-b"]


@pytest.mark.asyncio
async def test_delete_lane_behavior_is_explicit(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Removing a lane with members is rejected; removing an emptied lane succeeds."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    payload = _parallel_payload([issue.id for issue in lane_a], [issue.id for issue in lane_b])

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    dropping_with_members = {
        "name": "Parallel",
        "ordering_mode": "informational",
        "lanes": [{"id": "era-a", "name": "Era A", "order": 0}],
        "nodes": created.json()["nodes"],
    }
    rejected = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=dropping_with_members)
    assert rejected.status_code == 422
    assert "every node must reference an existing lane" in rejected.text

    dropping_empty_lane = {
        "name": "Parallel",
        "ordering_mode": "informational",
        "lanes": [{"id": "era-b", "name": "Era B", "order": 0}],
        "nodes": [
            {**node, "lane_id": "era-b", "position": position}
            for position, node in enumerate(
                [node for node in created.json()["nodes"] if node["lane_id"] != "era-a"]
            )
        ],
    }
    accepted = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=dropping_empty_lane)
    assert accepted.status_code == 200, accepted.text
    assert [lane["id"] for lane in accepted.json()["lanes"]] == ["era-b"]


def _parallel_payload_with_gates(
    lane_a: list[int],
    lane_b: list[int],
    *,
    checkpoint_index: int | None = None,
    convergence_from_b_to_a: int | None = None,
) -> PlanPayloadDict:
    """Build a two-lane informational plan with optional checkpoint/convergence."""
    nodes: list[PlanNodeDict] = []
    for position, issue_id in enumerate(lane_a):
        node: PlanNodeDict = {
            "id": f"a-{issue_id}",
            "node_type": "issue",
            "ref_id": issue_id,
            "lane_id": "era-a",
            "position": position,
            "is_checkpoint": position == checkpoint_index,
            "convergence_gate": None,
        }
        nodes.append(node)
    for position, issue_id in enumerate(lane_b):
        gate: list[dict[str, str]] = []
        if convergence_from_b_to_a is not None and position == 0:
            gate = [{"node_type": "issue", "node_id": f"a-{convergence_from_b_to_a}"}]
        nodes.append({
            "id": f"b-{issue_id}",
            "node_type": "issue",
            "ref_id": issue_id,
            "lane_id": "era-b",
            "position": position,
            "is_checkpoint": False,
            "convergence_gate": gate,
        })
    return {
        "name": "Gated plan",
        "ordering_mode": "informational",
        "lanes": [
            {"id": "era-a", "name": "Era A", "order": 0},
            {"id": "era-b", "name": "Era B", "order": 1},
        ],
        "nodes": nodes,
    }


@pytest.mark.asyncio
async def test_checkpoint_node_compiles_lane_blocking_rule(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A checkpoint node compiles a checkpoint rule that blocks the next node in the lane."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues])
    payload["nodes"][1]["is_checkpoint"] = True

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user.id)
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    checkpoint_rules = [r for r in rules if r.satisfaction_type == "checkpoint"]
    assert len(checkpoint_rules) == 1
    rule = checkpoint_rules[0]
    assert rule.source_id == issues[1].id
    assert rule.target_id == issues[2].id
    assert rule.checkpoint_issue_id == issues[1].id
    assert rule.note == f"continuity-plan:{plan_id}"


@pytest.mark.asyncio
async def test_checkpoint_on_last_node_compiles_no_rule(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A checkpoint on the last node in a lane has no downstream node and compiles no rule."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues])
    payload["nodes"][1]["is_checkpoint"] = True

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text

    rules = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    checkpoint_rules = [r for r in rules if r.satisfaction_type == "checkpoint"]
    assert checkpoint_rules == []


@pytest.mark.asyncio
async def test_convergence_gate_compiles_converged_rule(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate on a node compiles a converged rule waiting for the gate targets."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    payload = _parallel_payload_with_gates(
        [issue.id for issue in lane_a],
        [issue.id for issue in lane_b],
        convergence_from_b_to_a=lane_a[1].id,
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(ContinuityRule.user_id == user.id)
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    converged_rules = [r for r in rules if r.satisfaction_type == "converged"]
    assert len(converged_rules) == 1
    rule = converged_rules[0]
    assert rule.source_id == lane_b[0].id
    assert rule.target_id == lane_b[0].id
    assert rule.convergence_targets is not None
    assert len(rule.convergence_targets) == 1
    assert rule.convergence_targets[0]["type"] == "issue"
    assert rule.convergence_targets[0]["id"] == lane_a[1].id
    assert rule.note == f"continuity-plan:{plan_id}"


@pytest.mark.asyncio
async def test_convergence_gate_edit_save_reload_persists(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Editing convergence gates persists across save and reload."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3, 5)]
    await async_db.commit()
    payload = _parallel_payload_with_gates(
        [issue.id for issue in lane_a],
        [issue.id for issue in lane_b],
        convergence_from_b_to_a=lane_a[1].id,
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    # Edit: add convergence from second B node to first A node
    updated_nodes = created.json()["nodes"]
    for node in updated_nodes:
        if node["id"] == f"b-{lane_b[1].id}":
            node["convergence_gate"] = [{"node_type": "issue", "node_id": f"a-{lane_a[0].id}"}]
    update_payload = {
        "name": "Gated plan",
        "ordering_mode": "informational",
        "lanes": created.json()["lanes"],
        "nodes": updated_nodes,
    }
    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=update_payload)
    assert updated.status_code == 200, updated.text

    # Verify two converged rules exist
    rules = (
        await async_db.execute(
            select(ContinuityRule)
            .where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.satisfaction_type == "converged",
            )
        )
    ).scalars().all()
    assert len(rules) == 2

    # Reload and verify the plan data persists
    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert fetched.status_code == 200
    b_node = next(n for n in fetched.json()["nodes"] if n["id"] == f"b-{lane_b[1].id}")
    assert len(b_node["convergence_gate"]) == 1
    assert b_node["convergence_gate"][0]["node_id"] == f"a-{lane_a[0].id}"


@pytest.mark.asyncio
async def test_removing_convergence_gate_removes_only_plan_owned_rules(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Removing all convergence gates removes only the plan-owned converged rules."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    payload = _parallel_payload_with_gates(
        [issue.id for issue in lane_a],
        [issue.id for issue in lane_b],
        convergence_from_b_to_a=lane_a[1].id,
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    # Verify converged rule exists
    converged = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.satisfaction_type == "converged",
            )
        )
    ).scalars().all()
    assert len(converged) == 1

    # Update: remove convergence gate from all nodes
    updated_nodes = [
        {k: v for k, v in node.items() if k != "convergence_gate"}
        for node in created.json()["nodes"]
    ]
    for node in updated_nodes:
        node["convergence_gate"] = []
    update_payload = {
        "name": "Gated plan",
        "ordering_mode": "informational",
        "lanes": created.json()["lanes"],
        "nodes": updated_nodes,
    }
    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=update_payload)
    assert updated.status_code == 200, updated.text

    # Verify converged rules are removed
    converged_after = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.satisfaction_type == "converged",
            )
        )
    ).scalars().all()
    assert converged_after == []


@pytest.mark.asyncio
async def test_checkpoint_convergence_idempotent_recompile(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Re-saving a plan with checkpoints and convergence produces the same rules."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues])
    payload["nodes"][0]["is_checkpoint"] = True

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    first_rules = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.user_id == user.id).order_by(ContinuityRule.id)
        )
    ).scalars().all()
    first_count = len(first_rules)

    # Re-save with same payload
    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert updated.status_code == 200, updated.text

    second_rules = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.user_id == user.id).order_by(ContinuityRule.id)
        )
    ).scalars().all()
    assert len(second_rules) == first_count
    assert [(r.source_id, r.target_id, r.satisfaction_type) for r in second_rules] == [
        (r.source_id, r.target_id, r.satisfaction_type) for r in first_rules
    ]


@pytest.mark.asyncio
async def test_convergence_self_wait_rejected_by_schema(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate that references itself is rejected by schema validation."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues])
    payload["nodes"][0]["convergence_gate"] = [
        {"node_type": "issue", "node_id": "issue-" + str(issues[0].id)}
    ]

    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422
    assert "cannot wait for itself" in response.text


@pytest.mark.asyncio
async def test_checkpoint_on_non_issue_rejected_by_schema(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A checkpoint on a non-issue node is rejected by schema validation."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues])
    payload["nodes"][0]["node_type"] = "crossover"
    payload["nodes"][0]["is_checkpoint"] = True

    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 422
    assert "only allowed on issue nodes" in response.text


@pytest.mark.asyncio
async def test_convergence_cycle_rejected_before_save(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate that closes a dependency cycle is rejected before save."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    await async_db.commit()
    payload = {
        "name": "Cycle plan",
        "ordering_mode": "informational",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": "n-1",
                "node_type": "issue",
                "ref_id": issues[0].id,
                "lane_id": "main",
                "position": 0,
                "is_checkpoint": False,
                "convergence_gate": [{"node_type": "issue", "node_id": "n-2"}],
            },
            {
                "id": "n-2",
                "node_type": "issue",
                "ref_id": issues[1].id,
                "lane_id": "main",
                "position": 1,
                "is_checkpoint": False,
                "convergence_gate": [{"node_type": "issue", "node_id": "n-1"}],
            },
        ],
    }

    response = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "plan_convergence_cycle"


@pytest.mark.asyncio
async def test_convergence_gate_not_false_cyclic_in_readiness(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """A convergence gate node is not falsely reported as a self cycle in readiness."""
    user = await get_or_create_user_async(async_db)
    lane_a = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2)]
    lane_b = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(2, 4)]
    await async_db.commit()
    payload = _parallel_payload_with_gates(
        [issue.id for issue in lane_a],
        [issue.id for issue in lane_b],
        convergence_from_b_to_a=lane_a[1].id,
    )

    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    readiness = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert readiness.status_code == 200, readiness.text
    body = readiness.json()
    assert [d for d in body["plan_diagnostics"] if d["code"] == "plan_cycle_detected"] == []
    conv_node = next(n for n in body["nodes"] if n["node_id"] == f"b-{lane_b[0].id}")
    assert not any(d["code"] == "plan_cycle_detected" for d in conv_node.get("diagnostics", []))


@pytest.mark.asyncio
async def test_list_plans_returns_empty_for_user_with_no_plans(
    auth_client: AsyncClient,
) -> None:
    """The list endpoint returns an empty array when the user has saved no plans."""
    response = await auth_client.get("/api/v1/continuity-plans/")
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_plans_returns_owned_plans_with_summary(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """List returns each plan with name, ordering_mode, lane_count, step_count, and updated_at."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="b")
    await async_db.commit()

    parallel = _parallel_payload([issue_a.id], [issue_b.id])
    created = await auth_client.post("/api/v1/continuity-plans/", json=parallel)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    plan_name = created.json()["name"]

    strict = _plan_payload([issue_a.id], mode="strict_sequential")
    strict["name"] = "Strict"
    created2 = await auth_client.post("/api/v1/continuity-plans/", json=strict)
    assert created2.status_code == 201, created2.text

    response = await auth_client.get("/api/v1/continuity-plans/")
    assert response.status_code == 200, response.text
    items = response.json()
    ids = [item["id"] for item in items]
    assert plan_id in ids

    item = next(item for item in items if item["id"] == plan_id)
    assert item["name"] == plan_name
    assert item["ordering_mode"] == "informational"
    assert item["lane_count"] == 2
    assert item["step_count"] == 2
    assert "updated_at" in item


@pytest.mark.asyncio
async def test_list_plans_does_not_leak_other_users_plans(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Only plans owned by the authenticated user appear in the list."""
    from app.models.user import User as _User

    other = _User(username="other_list_user", created_at=datetime.now(UTC))
    async_db.add(other)
    await async_db.flush()
    await async_db.refresh(other)

    issue = await _make_issue(async_db, user_id=other.id, suffix="other")
    await async_db.commit()

    payload = _plan_payload([issue.id])
    other_plan = ContinuityPlan(
        user_id=other.id,
        name="Other plan",
        ordering_mode="informational",
        lanes_json=payload["lanes"],
        nodes_json=payload["nodes"],
    )
    async_db.add(other_plan)
    await async_db.flush()
    await async_db.refresh(other_plan)
    other_plan_id = other_plan.id

    response = await auth_client.get("/api/v1/continuity-plans/")
    assert response.status_code == 200, response.text
    items = response.json()
    assert all(item["id"] != other_plan_id for item in items)


@pytest.mark.asyncio
async def test_delete_plan_cascades_owned_rules_and_leaves_unrelated_rules_intact(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Deleting a plan removes only its generated rules; other users' and manual rules survive."""
    user = await get_or_create_user_async(async_db)
    plan_issue_1 = await _make_issue(async_db, user_id=user.id, suffix="plan1")
    plan_issue_2 = await _make_issue(async_db, user_id=user.id, suffix="plan2")
    manual_issue = await _make_issue(async_db, user_id=user.id, suffix="manual")
    await async_db.commit()

    plan_payload = _plan_payload([plan_issue_1.id, plan_issue_2.id], mode="strict_sequential")
    plan_payload["name"] = "Plan to delete"
    created = await auth_client.post("/api/v1/continuity-plans/", json=plan_payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rules_before = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    plan_marker = f"continuity-plan:{plan_id}"
    assert any(rule.note == plan_marker for rule in rules_before)

    manual_rule = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=manual_issue.id,
        target_type="issue",
        target_id=plan_issue_1.id,
        satisfaction_type="item_read",
        note="manual-standalone",
    )
    async_db.add(manual_rule)
    await async_db.commit()

    rules_after_manual = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert len(rules_after_manual) >= 2

    delete_response = await auth_client.delete(f"/api/v1/continuity-plans/{plan_id}")
    assert delete_response.status_code == 204, delete_response.text

    remaining = (
        await async_db.execute(
            select(ContinuityRule).where(
                ContinuityRule.user_id == user.id,
                ContinuityRule.note == plan_marker,
            )
        )
    ).scalars().all()
    assert remaining == []

    standalone = (
        await async_db.execute(
            select(ContinuityRule).where(ContinuityRule.note == "manual-standalone")
        )
    ).scalar_one_or_none()
    assert standalone is not None


@pytest.mark.asyncio
async def test_list_plans_orders_by_last_saved(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """The list returns plans sorted by most recently updated first."""
    from sqlalchemy import select
    from datetime import timedelta

    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="order")
    await async_db.commit()

    old_payload = _plan_payload([issue.id])
    old_payload["name"] = "Older"
    old_resp = await auth_client.post("/api/v1/continuity-plans/", json=old_payload)
    assert old_resp.status_code == 201, old_resp.text
    old_id = old_resp.json()["id"]

    await async_db.commit()
    old_plan = (
        await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.id == old_id))
    ).scalar_one()
    old_plan.updated_at = datetime.now(UTC) - timedelta(hours=1)
    await async_db.flush()
    await async_db.commit()

    new_payload = _plan_payload([issue.id])
    new_payload["name"] = "Newer"
    new_resp = await auth_client.post("/api/v1/continuity-plans/", json=new_payload)
    assert new_resp.status_code == 201, new_resp.text
    new_id = new_resp.json()["id"]

    response = await auth_client.get("/api/v1/continuity-plans/")
    assert response.status_code == 200, response.text
    ids = [item["id"] for item in response.json()]
    assert ids.index(new_id) < ids.index(old_id)