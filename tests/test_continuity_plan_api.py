"""API coverage for persisted continuity plans and explicit rule compilation."""

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
from tests.conftest import get_or_create_user_async


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


def _plan_payload(issue_ids: list[int], *, mode: str = "informational") -> dict[str, object]:
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
) -> dict[str, object]:
    """Build a two-lane informational plan payload with one issue node per entry."""
    nodes: list[dict[str, object]] = []
    for position, issue_id in enumerate(lane_a):
        nodes.append(
            {
                "id": f"a-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "era-a",
                "position": position,
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
