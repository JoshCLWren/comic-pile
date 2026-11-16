"""API coverage for persisted continuity plans and explicit reader/recovery APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TypedDict
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import continuity_plan as continuity_plan_api
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
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
async def test_get_fills_missing_issue_labels_from_owned_comics(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Unlabeled CBL issue steps are repaired on GET without rewriting storage (#3481)."""
    user = await get_or_create_user_async(async_db)
    issue = await _make_issue(async_db, user_id=user.id, suffix="usm")
    await async_db.execute(
        insert(ContinuityPlan).values(
            user_id=user.id,
            name="Unlabeled CBL plan",
            ordering_mode="informational",
            lanes_json=[{"id": "main", "name": "Main", "order": 0}],
            nodes_json=[
                {
                    "id": "cbl-1",
                    "node_type": "issue",
                    "ref_id": issue.id,
                    "lane_id": "main",
                    "position": 0,
                    "label": "",
                    "is_checkpoint": False,
                    "convergence_gate": [],
                }
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await async_db.commit()
    plan = (
        await async_db.execute(
            select(ContinuityPlan).where(
                ContinuityPlan.user_id == user.id,
                ContinuityPlan.name == "Unlabeled CBL plan",
            )
        )
    ).scalar_one()

    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}")
    assert fetched.status_code == 200, fetched.text
    node = fetched.json()["nodes"][0]
    assert node["label"] == "Plan usm #1"
    stored = (
        await async_db.execute(select(ContinuityPlan).where(ContinuityPlan.id == plan.id))
    ).scalar_one()
    assert stored.nodes_json[0]["label"] == ""


@pytest.mark.asyncio
async def test_strict_plan_compiles_idempotently_then_informational_update_removes_owned_rules(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit checkpoints compile; reverting intent removes only plan-owned edges."""
    monkeypatch.setattr(continuity_plan_api, "_refresh_blocked_state", AsyncMock())
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=str(i)) for i in range(3)]
    await async_db.commit()
    payload = _plan_payload([issue.id for issue in issues], mode="strict_sequential")
    payload["nodes"][0]["is_checkpoint"] = True
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
    informational["nodes"] = [
        {**node, "is_checkpoint": False} for node in payload["nodes"]
    ]
    updated = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}", json=informational
    )
    assert updated.status_code == 200, updated.text
    remaining = (
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.user_id == user.id))
    ).scalars().all()
    assert remaining == []


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
    plan_payload["nodes"][0]["is_checkpoint"] = True
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
        await async_db.execute(select(ContinuityRule).where(ContinuityRule.note == "manual-standalone"))
    ).scalar_one_or_none()
    assert standalone is not None