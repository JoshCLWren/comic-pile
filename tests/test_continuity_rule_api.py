"""API coverage for generalized continuity-rule CRUD."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import continuity_rule as continuity_rule_api
from app.models.continuity_rule import ContinuityRule
from app.models.dependency_group import DependencyGroup
from app.models.issue import Issue
from app.models.thread import Thread
from app.models.user import User
from tests.conftest import get_or_create_user_async


async def _make_issue(async_db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned thread and issue for continuity tests."""
    thread = Thread(
        title=f"Continuity {suffix}",
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


async def _make_group(async_db: AsyncSession, *, user_id: int, suffix: str) -> DependencyGroup:
    """Create one owned crossover node for continuity tests."""
    group = DependencyGroup(user_id=user_id, name=f"Crossover {suffix}")
    async_db.add(group)
    await async_db.flush()
    return group


def _payload(source_type: str, source_id: int, target_type: str, target_id: int) -> dict[str, object]:
    """Build the common item-read rule payload."""
    return {
        "source_type": source_type,
        "source_id": source_id,
        "target_type": target_type,
        "target_id": target_id,
        "satisfaction_type": "item_read",
    }


@pytest.mark.asyncio
async def test_crud_supports_all_node_pairings_and_delete(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """All issue/crossover pairings can be created, read, updated, listed, and deleted."""
    user = await get_or_create_user_async(async_db)
    issues = [await _make_issue(async_db, user_id=user.id, suffix=f"issue-{index}") for index in range(4)]
    groups = [await _make_group(async_db, user_id=user.id, suffix=f"group-{index}") for index in range(4)]
    await async_db.commit()

    payloads = [
        _payload("issue", issues[0].id, "issue", issues[1].id),
        _payload("issue", issues[2].id, "crossover", groups[0].id),
        _payload("crossover", groups[1].id, "issue", issues[3].id),
        _payload("crossover", groups[2].id, "crossover", groups[3].id),
    ]
    created: list[dict[str, object]] = []
    for payload in payloads:
        response = await auth_client.post("/api/v1/continuity-rules/", json=payload)
        assert response.status_code == 201, response.text
        created.append(response.json())

    listed = await auth_client.get("/api/v1/continuity-rules/")
    assert listed.status_code == 200
    assert len(listed.json()) == 4

    rule_id = int(created[0]["id"])
    fetched = await auth_client.get(f"/api/v1/continuity-rules/{rule_id}")
    assert fetched.status_code == 200
    assert fetched.json()["source_type"] == "issue"
    assert fetched.json()["target_type"] == "issue"

    updated_payload = dict(payloads[0])
    updated_payload["note"] = "Read this first"
    updated = await auth_client.put(
        f"/api/v1/continuity-rules/{rule_id}",
        json=updated_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["note"] == "Read this first"

    deleted = await auth_client.delete(f"/api/v1/continuity-rules/{rule_id}")
    assert deleted.status_code == 204
    missing = await auth_client.get(f"/api/v1/continuity-rules/{rule_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_direct_and_transitive_cycles_are_rejected(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Cycle detection rejects both immediate reversals and longer mixed-node loops."""
    user = await get_or_create_user_async(async_db)
    issue_a = await _make_issue(async_db, user_id=user.id, suffix="cycle-a")
    issue_b = await _make_issue(async_db, user_id=user.id, suffix="cycle-b")
    group = await _make_group(async_db, user_id=user.id, suffix="cycle")
    await async_db.commit()

    first = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=_payload("issue", issue_a.id, "issue", issue_b.id),
    )
    assert first.status_code == 201

    direct = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=_payload("issue", issue_b.id, "issue", issue_a.id),
    )
    assert direct.status_code == 409
    assert direct.json()["detail"]["code"] == "continuity_cycle"

    second = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=_payload("issue", issue_b.id, "crossover", group.id),
    )
    assert second.status_code == 201

    transitive = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=_payload("crossover", group.id, "issue", issue_a.id),
    )
    assert transitive.status_code == 409
    assert transitive.json()["detail"] == {
        "code": "continuity_cycle",
        "source": {"type": "crossover", "id": group.id},
        "target": {"type": "issue", "id": issue_a.id},
    }


@pytest.mark.asyncio
async def test_other_users_rules_are_hidden_and_unreferenceable(
    auth_client: AsyncClient, async_db: AsyncSession
) -> None:
    """Owned reads and reference validation do not expose another user's graph."""
    current_user = await get_or_create_user_async(async_db)
    owned_issue = await _make_issue(async_db, user_id=current_user.id, suffix="owned")
    other_user = User(username="continuity-other", email="continuity-other@example.com")
    async_db.add(other_user)
    await async_db.flush()
    foreign_issue = await _make_issue(async_db, user_id=other_user.id, suffix="foreign")
    foreign_group = await _make_group(async_db, user_id=other_user.id, suffix="foreign")
    foreign_rule = ContinuityRule(
        user_id=other_user.id,
        source_type="issue",
        source_id=foreign_issue.id,
        target_type="crossover",
        target_id=foreign_group.id,
        satisfaction_type="item_read",
    )
    async_db.add(foreign_rule)
    await async_db.commit()

    listed = await auth_client.get("/api/v1/continuity-rules/")
    assert listed.status_code == 200
    assert all(rule["id"] != foreign_rule.id for rule in listed.json())

    fetched = await auth_client.get(f"/api/v1/continuity-rules/{foreign_rule.id}")
    assert fetched.status_code == 404

    foreign_reference = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=_payload("issue", owned_issue.id, "crossover", foreign_group.id),
    )
    assert foreign_reference.status_code == 404


@pytest.mark.asyncio
async def test_continuity_mutations_invalidate_related_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Continuity mutations clear both continuity and legacy blocked-state cache families."""
    invalidate = AsyncMock()
    monkeypatch.setattr(continuity_rule_api, "invalidate_cache", invalidate)

    await continuity_rule_api._invalidate_continuity_caches(42)

    invalidate.assert_any_await("cache:continuity:*:User:42:*")
    invalidate.assert_any_await("cache:get_blocked_thread_ids:42:")
    invalidate.assert_any_await("cache:list_threads:User:42:*")
    invalidate.assert_any_await("cache:get_thread_blocking_info:*:User:42:")
    invalidate.assert_any_await("cache:get_threads_blocking_info:*:User:42:")
    assert invalidate.await_count == 5
