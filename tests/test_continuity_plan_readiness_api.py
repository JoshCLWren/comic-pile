"""API coverage for live per-node readiness of saved continuity plans."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from tests.conftest import get_or_create_user_async


async def _make_thread_with_issues(
    async_db: AsyncSession,
    *,
    user_id: int,
    suffix: str,
    issue_count: int = 2,
) -> tuple[Thread, list[Issue]]:
    """Create one owned active thread with deterministic unread issues."""
    thread = Thread(
        title=f"PlanReadiness {suffix}",
        format="comic",
        issues_remaining=issue_count,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=issue_count,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issues = [
        Issue(
            thread_id=thread.id,
            issue_number=str(position),
            position=position,
            status="unread",
        )
        for position in range(1, issue_count + 1)
    ]
    async_db.add_all(issues)
    await async_db.flush()
    thread.next_unread_issue_id = issues[0].id
    return thread, issues


def _plan_payload(
    nodes: list[dict[str, object]],
    *,
    mode: str = "informational",
) -> dict[str, object]:
    """Build a one-lane plan payload around arbitrary node descriptors."""
    return {
        "name": "Readiness plan",
        "ordering_mode": mode,
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": nodes,
    }


def _issue_node(issue: Issue, *, position: int) -> dict[str, object]:
    """Build one issue node descriptor for a plan payload."""
    return {
        "id": f"issue-{issue.id}",
        "node_type": "issue",
        "ref_id": issue.id,
        "lane_id": "main",
        "position": position,
    }


@pytest.mark.asyncio
async def test_plan_readiness_reports_readable_blocked_and_complete_states(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Live plan readiness agrees with direct readiness for each visible node."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="states-source", issue_count=1
    )
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="states-target", issue_count=1
    )
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=target_issues[0].id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            [
                _issue_node(source_issues[0], position=0),
                _issue_node(target_issues[0], position=1),
            ]
        ),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_id"] == plan_id
    assert body["ordering_mode"] == "informational"

    nodes = {node["node_id"]: node for node in body["nodes"]}
    source_node = nodes[f"issue-{source_issues[0].id}"]
    target_node = nodes[f"issue-{target_issues[0].id}"]
    assert source_node["is_readable"] is True
    assert source_node["is_complete"] is False
    assert source_node["blockers"] == []
    assert target_node["is_readable"] is False
    assert target_node["blockers"][0]["causing_issue_ids"] == [source_issues[0].id]

    source_issues[0].status = "read"
    await async_db.commit()
    after = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    after_body = after.json()
    after_nodes = {node["node_id"]: node for node in after_body["nodes"]}
    assert after_nodes[f"issue-{source_issues[0].id}"]["is_complete"] is True
    assert after_nodes[f"issue-{target_issues[0].id}"]["is_readable"] is True
    summary = after_body["summary"]
    assert summary["total"] == 2
    assert summary["complete"] == 1
    assert summary["readable"] == 1
    assert summary["blocked"] == 0
    assert summary["unavailable"] == 0


@pytest.mark.asyncio
async def test_plan_readiness_include_chains_resolves_bounded_prerequisites(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Opt-in chain resolution explains a blocked node without another call."""
    user = await get_or_create_user_async(async_db)
    first_thread, first_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-first", issue_count=1
    )
    second_thread, second_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-second", issue_count=1
    )
    _third_thread, third_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-third", issue_count=1
    )
    async_db.add_all(
        [
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=first_issues[0].id,
                target_type="issue",
                target_id=second_issues[0].id,
                satisfaction_type="item_read",
            ),
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=second_issues[0].id,
                target_type="issue",
                target_id=third_issues[0].id,
                satisfaction_type="item_read",
            ),
        ]
    )
    await async_db.commit()
    assert first_thread.id and second_thread.id  # keep fixture typing explicit

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            [
                _issue_node(first_issues[0], position=0),
                _issue_node(third_issues[0], position=1),
            ]
        ),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    response = await auth_client.get(
        f"/api/v1/continuity-plans/{plan_id}/readiness?include_chains=true"
    )
    assert response.status_code == 200, response.text
    nodes = {node["node_id"]: node for node in response.json()["nodes"]}
    third_node = nodes[f"issue-{third_issues[0].id}"]
    assert third_node["is_readable"] is False
    assert third_node["chains"], "blocked node should expose prerequisite chains"
    first_chain = third_node["chains"][0]
    assert first_chain[0]["node_type"] == "issue"
    assert first_chain[0]["is_readable"] is False
    assert any(step["node_id"] == first_issues[0].id for step in first_chain)
    assert any(step["is_readable"] for step in first_chain)


@pytest.mark.asyncio
async def test_plan_readiness_reports_dangling_reference_without_crashing(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A deleted referenced node degrades to a structured dangling diagnostic."""
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="dangling", issue_count=1
    )
    await async_db.commit()
    payload = _plan_payload(
        [
            _issue_node(issues[0], position=0),
            {
                "id": "ghost",
                "node_type": "issue",
                "ref_id": 987654321,
                "lane_id": "main",
                "position": 1,
            },
        ]
    )
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 422
    assert created.json()["detail"]["code"] == "dangling_plan_reference"

    valid_payload = _plan_payload(
        [
            _issue_node(issues[0], position=0),
            {
                "id": "ghost",
                "node_type": "issue",
                "ref_id": 987654321,
                "lane_id": "main",
                "position": 1,
            },
        ]
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="Ghost plan",
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=list(valid_payload["nodes"]),
    )
    async_db.add(plan)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    nodes = {node["node_id"]: node for node in body["nodes"]}
    ghost = nodes["ghost"]
    assert ghost["is_readable"] is False
    assert ghost["is_complete"] is False
    codes = [diagnostic["code"] for diagnostic in ghost["diagnostics"]]
    assert codes == ["dangling_plan_reference"]
    assert body["summary"]["unavailable"] == 1


@pytest.mark.asyncio
async def test_plan_readiness_dangling_diagnostic_survives_cross_type_ref_id_collision(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A malformed node whose ref_id collides with a different type is still dangling."""
    user = await get_or_create_user_async(async_db)
    thread, _ = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="collision", issue_count=1
    )
    await async_db.commit()

    raw_payload = _plan_payload(
        [
            {
                "id": "malformed-cross",
                "node_type": "ghost",
                "ref_id": thread.id,
                "lane_id": "main",
                "position": 1,
            },
        ]
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="Collision plan",
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=list(raw_payload["nodes"]),
    )
    async_db.add(plan)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    nodes = {node["node_id"]: node for node in body["nodes"]}
    node = nodes["malformed-cross"]
    assert node["is_readable"] is False
    codes = [diagnostic["code"] for diagnostic in node["diagnostics"]]
    assert codes == ["dangling_plan_reference"]
    assert body["summary"]["unavailable"] == 1


@pytest.mark.asyncio
async def test_plan_readiness_detects_plan_owned_rule_cycle(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Cyclic plan-owned rules are surfaced as structured diagnostics."""
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="cycle", issue_count=3
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            [
                _issue_node(issues[0], position=0),
                _issue_node(issues[1], position=1),
                _issue_node(issues[2], position=2),
            ],
            mode="strict_sequential",
        ),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=issues[2].id,
            target_type="issue",
            target_id=issues[0].id,
            satisfaction_type="item_read",
            note=f"continuity-plan:{plan_id}",
        )
    )
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert response.status_code == 200, response.text
    body = response.json()
    plan_codes = {diagnostic["code"] for diagnostic in body["plan_diagnostics"]}
    assert "plan_cycle_detected" in plan_codes
    node_cycle_codes = {
        code
        for node in body["nodes"]
        for code in (diagnostic["code"] for diagnostic in node["diagnostics"])
    }
    assert "plan_cycle_detected" in node_cycle_codes


@pytest.mark.asyncio
async def test_plan_readiness_hides_foreign_plans(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Readiness of another user's plan resolves to the ownership 404 boundary."""
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="foreign", issue_count=1
    )
    other_user = User(username="plan-foreign", email="plan-foreign@example.com")
    async_db.add(other_user)
    await async_db.flush()
    await async_db.commit()
    plan = ContinuityPlan(
        user_id=other_user.id,
        name="Foreign",
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[_issue_node(issues[0], position=0)],
    )
    async_db.add(plan)
    await async_db.commit()

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan.id}/readiness")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_plan_readiness_includes_thread_and_complete_thread_nodes(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Thread nodes report completion based on next-unread state."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="thread-node", issue_count=2
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            [
                {
                    "id": f"thread-{thread.id}",
                    "node_type": "thread",
                    "ref_id": thread.id,
                    "lane_id": "main",
                    "position": 0,
                }
            ]
        ),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    response = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    assert response.status_code == 200, response.text
    node = response.json()["nodes"][0]
    assert node["node_type"] == "thread"
    assert node["is_readable"] is True
    assert node["is_complete"] is False
    assert node["evaluated_issue_id"] == issues[0].id

    for issue in issues:
        issue.status = "read"
    thread.next_unread_issue_id = None
    await async_db.commit()
    completed = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}/readiness")
    completed_node = completed.json()["nodes"][0]
    assert completed_node["is_complete"] is True
