"""API coverage for structured continuity readiness evaluation."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule, ContinuityRuleSelectedMember
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
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
        title=f"Readiness {suffix}",
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


async def _make_group(
    async_db: AsyncSession,
    *,
    user_id: int,
    suffix: str,
    issue_ids: list[int] | None = None,
    thread_ids: list[int] | None = None,
) -> DependencyGroup:
    """Create one crossover with optional issue and thread memberships."""
    group = DependencyGroup(user_id=user_id, name=f"Crossover {suffix}")
    async_db.add(group)
    await async_db.flush()
    for issue_id in issue_ids or []:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue_id))
    for thread_id in thread_ids or []:
        async_db.add(DependencyGroupMembership(group_id=group.id, thread_id=thread_id))
    await async_db.flush()
    return group


def _rule(
    *,
    user_id: int,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    satisfaction_type: str,
    checkpoint_issue_id: int | None = None,
) -> ContinuityRule:
    """Build a continuity rule for readiness tests."""
    return ContinuityRule(
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        target_type=target_type,
        target_id=target_id,
        satisfaction_type=satisfaction_type,
        checkpoint_issue_id=checkpoint_issue_id,
    )


@pytest.mark.asyncio
async def test_issue_and_thread_readiness_follow_item_read_rule(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An unread prerequisite blocks both issue and next-unread thread readiness."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="source", issue_count=1
    )
    target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="target", issue_count=1
    )
    async_db.add(
        _rule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=target_issues[0].id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    issue_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert issue_response.status_code == 200, issue_response.text
    payload = issue_response.json()
    assert payload["is_readable"] is False
    assert payload["blockers"][0]["causing_issue_ids"] == [source_issues[0].id]
    assert payload["blockers"][0]["satisfaction_type"] == "item_read"

    thread_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "thread", "node_id": target_thread.id},
    )
    assert thread_response.status_code == 200, thread_response.text
    assert thread_response.json()["evaluated_issue_id"] == target_issues[0].id
    assert thread_response.json()["is_readable"] is False

    source_issues[0].status = "read"
    await async_db.commit()
    readable_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert readable_response.status_code == 200
    assert readable_response.json()["is_readable"] is True
    assert readable_response.json()["blockers"] == []


@pytest.mark.asyncio
async def test_checkpoint_and_selected_member_policies_report_only_unsatisfied_issues(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Checkpoint and selected-member policies expose structured causing issue IDs."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="policies-source", issue_count=3
    )
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="policies-target", issue_count=2
    )
    source_group = await _make_group(
        async_db,
        user_id=user.id,
        suffix="selected",
        issue_ids=[source_issues[1].id, source_issues[2].id],
    )
    checkpoint_rule = _rule(
        user_id=user.id,
        source_type="issue",
        source_id=source_issues[0].id,
        target_type="issue",
        target_id=target_issues[0].id,
        satisfaction_type="checkpoint",
        checkpoint_issue_id=source_issues[1].id,
    )
    selected_rule = _rule(
        user_id=user.id,
        source_type="crossover",
        source_id=source_group.id,
        target_type="issue",
        target_id=target_issues[1].id,
        satisfaction_type="selected_members_read",
    )
    selected_rule.selected_members = [
        ContinuityRuleSelectedMember(issue_id=source_issues[1].id),
        ContinuityRuleSelectedMember(issue_id=source_issues[2].id),
    ]
    source_issues[1].status = "read"
    async_db.add_all([checkpoint_rule, selected_rule])
    await async_db.commit()

    checkpoint_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert checkpoint_response.status_code == 200
    assert checkpoint_response.json()["is_readable"] is True

    selected_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[1].id},
    )
    assert selected_response.status_code == 200, selected_response.text
    blocker = selected_response.json()["blockers"][0]
    assert blocker["satisfaction_type"] == "selected_members_read"
    assert blocker["causing_member_issue_ids"] == [source_issues[2].id]


@pytest.mark.asyncio
async def test_crossover_readiness_propagates_member_blockers_across_multiple_memberships(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """One blocked unread issue makes every crossover containing it unreadable."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="multi-source", issue_count=1
    )
    target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="multi-target", issue_count=1
    )
    first_group = await _make_group(
        async_db,
        user_id=user.id,
        suffix="first",
        issue_ids=[target_issues[0].id],
    )
    second_group = await _make_group(
        async_db,
        user_id=user.id,
        suffix="second",
        thread_ids=[target_thread.id],
    )
    async_db.add(
        _rule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=target_issues[0].id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    for group_id in (first_group.id, second_group.id):
        response = await auth_client.post(
            "/api/v1/continuity/readiness",
            json={"node_type": "crossover", "node_id": group_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_readable"] is False
        assert response.json()["blockers"][0]["causing_issue_ids"] == [source_issues[0].id]


@pytest.mark.asyncio
async def test_parallel_unruled_nodes_are_readable_and_foreign_nodes_are_hidden(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Independent branches stay readable and ownership failures use a 404 boundary."""
    user = await get_or_create_user_async(async_db)
    _owned_thread, owned_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="parallel", issue_count=2
    )
    other_user = User(username="readiness-other", email="readiness-other@example.com")
    async_db.add(other_user)
    await async_db.flush()
    _foreign_thread, foreign_issues = await _make_thread_with_issues(
        async_db, user_id=other_user.id, suffix="foreign", issue_count=1
    )
    await async_db.commit()

    for issue in owned_issues:
        response = await auth_client.post(
            "/api/v1/continuity/readiness",
            json={"node_type": "issue", "node_id": issue.id},
        )
        assert response.status_code == 200
        assert response.json()["is_readable"] is True
        assert response.json()["blockers"] == []

    foreign_response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": foreign_issues[0].id},
    )
    assert foreign_response.status_code == 404
