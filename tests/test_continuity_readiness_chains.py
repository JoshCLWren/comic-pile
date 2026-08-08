"""Regression coverage for transitive continuity prerequisite traversal."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.continuity_readiness as readiness
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one active thread with one unread issue."""
    thread = Thread(
        title=f"Chain {suffix}",
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
    thread.next_unread_issue_id = issue.id
    return issue


def _item_rule(*, user_id: int, source_id: int, target_id: int) -> ContinuityRule:
    """Create one issue-to-issue item-read rule."""
    return ContinuityRule(
        user_id=user_id,
        source_type="issue",
        source_id=source_id,
        target_type="issue",
        target_id=target_id,
        satisfaction_type="item_read",
    )


@pytest.mark.asyncio
async def test_transitive_chain_recommends_first_readable_leaf(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A blocked by B and B by C recommends C while preserving the full chain."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="A")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="B")
    issue_c = await _make_issue(async_db, user_id=user.id, suffix="C")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=issue_b.id, target_id=issue_a.id),
            _item_rule(user_id=user.id, source_id=issue_c.id, target_id=issue_b.id),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": issue_a.id},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_readable"] is False
    assert [node["node_id"] for node in payload["chains"][0]["nodes"]] == [
        issue_b.id,
        issue_c.id,
    ]
    assert payload["readable_prerequisites"] == [
        {
            "node_type": "issue",
            "node_id": issue_c.id,
            "label": f"Chain C #{issue_c.issue_number}",
            "is_readable": True,
        }
    ]
    assert payload["diagnostics"] == []


@pytest.mark.asyncio
async def test_branching_chain_is_deterministic_and_preserves_every_leaf(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Multiple prerequisite branches return stable paths and unique readable leaves."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="target")
    left = await _make_issue(async_db, user_id=user.id, suffix="left")
    right = await _make_issue(async_db, user_id=user.id, suffix="right")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=right.id, target_id=target.id),
            _item_rule(user_id=user.id, source_id=left.id, target_id=target.id),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [chain["nodes"][0]["node_id"] for chain in payload["chains"]] == sorted(
        [left.id, right.id]
    )
    assert [node["node_id"] for node in payload["readable_prerequisites"]] == sorted(
        [left.id, right.id]
    )


@pytest.mark.asyncio
async def test_legacy_cycle_returns_structured_diagnostic_instead_of_recursing(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Malformed legacy cycles terminate with a structured cycle diagnostic."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="cycle-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="cycle-b")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=issue_b.id, target_id=issue_a.id),
            _item_rule(user_id=user.id, source_id=issue_a.id, target_id=issue_b.id),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": issue_a.id},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chains"] == []
    assert payload["readable_prerequisites"] == []
    assert payload["diagnostics"][0]["code"] == "cycle_detected"


@pytest.mark.asyncio
async def test_traversal_node_budget_returns_structured_diagnostic(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Traversal stops at the configured node budget instead of expanding indefinitely."""
    user = await get_or_create_user_async(async_db)
    target = await _make_issue(async_db, user_id=user.id, suffix="budget-target")
    middle = await _make_issue(async_db, user_id=user.id, suffix="budget-middle")
    leaf = await _make_issue(async_db, user_id=user.id, suffix="budget-leaf")
    async_db.add_all(
        [
            _item_rule(user_id=user.id, source_id=middle.id, target_id=target.id),
            _item_rule(user_id=user.id, source_id=leaf.id, target_id=middle.id),
        ]
    )
    await async_db.commit()
    monkeypatch.setattr(readiness, "MAX_TRAVERSAL_NODES", 1)

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target.id},
    )

    assert response.status_code == 200
    diagnostic = response.json()["diagnostics"][0]
    assert diagnostic == {
        "code": "node_limit_exceeded",
        "node_type": "issue",
        "node_id": leaf.id,
        "limit": 1,
    }
