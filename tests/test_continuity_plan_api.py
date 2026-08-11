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
