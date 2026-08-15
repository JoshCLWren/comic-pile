"""API coverage for structured continuity readiness evaluation."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.continuity_readiness as readiness
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
    convergence_targets: list[dict[str, object]] | None = None,
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
        convergence_targets=convergence_targets,
    )


@pytest.mark.asyncio
async def test_issue_and_thread_readiness_follow_item_read_rule(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An unread prerequisite blocks both issue and next-unread thread readiness.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
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
    """Checkpoint and selected-member policies expose structured causing issue IDs.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
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
    """One blocked unread issue makes every crossover containing it unreadable.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
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
    """Independent branches stay readable and ownership failures use a 404 boundary.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
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


@pytest.mark.asyncio
async def test_membership_collection_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crossover-membership collection beyond its cap fails before evaluation.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.
        monkeypatch: Pytest fixture used to reduce the production cap for this regression.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="membership-limit", issue_count=2
    )
    group = await _make_group(
        async_db,
        user_id=user.id,
        suffix="membership-limit",
        issue_ids=[issue.id for issue in issues],
    )
    await async_db.commit()
    monkeypatch.setattr(readiness, "MAX_GRAPH_MEMBERSHIPS", 1)

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "crossover", "node_id": group.id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "continuity_graph_too_large",
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_continuity_chains_resolves_transitive_path_and_readable_leaf(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """The chains endpoint returns bounded prerequisite paths and readable leaves.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-target", issue_count=1
    )
    _middle_thread, middle_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-middle", issue_count=1
    )
    _leaf_thread, leaf_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-leaf", issue_count=1
    )
    async_db.add_all(
        [
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=middle_issues[0].id,
                target_type="issue",
                target_id=target_issues[0].id,
                satisfaction_type="item_read",
            ),
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=leaf_issues[0].id,
                target_type="issue",
                target_id=middle_issues[0].id,
                satisfaction_type="item_read",
            ),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["node_type"] == "issue"
    assert payload["node_id"] == target_issues[0].id
    assert payload["evaluated_issue_id"] is None
    direct_blockers = payload["direct_blockers"]
    assert [blocker["source_id"] for blocker in direct_blockers] == [middle_issues[0].id]
    chains = payload["chains"]
    assert [[node["node_id"] for node in path] for path in chains] == [
        [middle_issues[0].id, leaf_issues[0].id]
    ]
    readable = payload["readable_prerequisites"]
    assert [node["node_id"] for node in readable] == [leaf_issues[0].id]
    assert readable[0]["is_readable"] is True
    assert payload["diagnostics"] == []


@pytest.mark.asyncio
async def test_continuity_chains_reports_structured_cycle_diagnostics(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A legacy cycle yields empty chains plus a structured cycle diagnostic.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _first_thread, first_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="cycle-a", issue_count=1
    )
    _second_thread, second_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="cycle-b", issue_count=1
    )
    async_db.add_all(
        [
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=second_issues[0].id,
                target_type="issue",
                target_id=first_issues[0].id,
                satisfaction_type="item_read",
            ),
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=first_issues[0].id,
                target_type="issue",
                target_id=second_issues[0].id,
                satisfaction_type="item_read",
            ),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "issue", "node_id": first_issues[0].id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["chains"] == []
    assert payload["readable_prerequisites"] == []
    diagnostics = payload["diagnostics"]
    assert diagnostics[0]["code"] == "cycle_detected"
    assert diagnostics[0]["node_id"] in {first_issues[0].id, second_issues[0].id}


@pytest.mark.asyncio
async def test_continuity_chains_returns_converging_parallel_branches(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Two parallel prerequisites converge into one target with deterministic paths.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converging-target", issue_count=1
    )
    _left_thread, left_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converging-left", issue_count=1
    )
    _right_thread, right_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converging-right", issue_count=1
    )
    async_db.add_all(
        [
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=left_issues[0].id,
                target_type="issue",
                target_id=target_issues[0].id,
                satisfaction_type="item_read",
            ),
            _rule(
                user_id=user.id,
                source_type="issue",
                source_id=right_issues[0].id,
                target_type="issue",
                target_id=target_issues[0].id,
                satisfaction_type="item_read",
            ),
        ]
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    chain_sources = sorted(
        [path[0]["node_id"] for path in payload["chains"]]
    )
    assert chain_sources == sorted([left_issues[0].id, right_issues[0].id])
    leaves = sorted(node["node_id"] for node in payload["readable_prerequisites"])
    assert leaves == sorted([left_issues[0].id, right_issues[0].id])


@pytest.mark.asyncio
async def test_continuity_chains_returns_empty_for_readable_node_with_no_chain(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A readable node with no prerequisites returns empty chain and diagnostic state.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="readable-no-chain", issue_count=1
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "issue", "node_id": issues[0].id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["direct_blockers"] == []
    assert payload["chains"] == []
    assert payload["readable_prerequisites"] == []
    assert payload["diagnostics"] == []


@pytest.mark.asyncio
async def test_continuity_chains_thread_endpoint_evaluates_next_unread_issue(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A thread chain request exposes the next unread issue id in the response.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="thread-chain", issue_count=2
    )
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="thread-chain-source", issue_count=1
    )
    async_db.add(
        _rule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=issues[0].id,
            satisfaction_type="item_read",
        )
    )
    await async_db.commit()

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "thread", "node_id": thread.id},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evaluated_issue_id"] == issues[0].id
    assert [blocker["source_id"] for blocker in payload["direct_blockers"]] == [
        source_issues[0].id
    ]


@pytest.mark.asyncio
async def test_continuity_chains_membership_collection_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chains endpoint surfaces the graph-too-large cap before traversal.

    The ``/api/v1/continuity/chains`` endpoint shares ``_load_snapshot`` with the
    readiness endpoint and therefore must surface a 422 with the
    ``continuity_graph_too_large`` detail when a crossover membership collection
    exceeds its cap. This regression guarantees the chains route does not bypass
    the bounded snapshot gate or return an unstructured 422 to the frontend.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.
        monkeypatch: Pytest fixture used to shrink the membership cap for this
            regression.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="chains-membership-limit", issue_count=2
    )
    await _make_group(
        async_db,
        user_id=user.id,
        suffix="chains-membership-limit",
        issue_ids=[issue.id for issue in issues],
    )
    await async_db.commit()
    monkeypatch.setattr(readiness, "MAX_GRAPH_MEMBERSHIPS", 1)

    response = await auth_client.post(
        "/api/v1/continuity/chains",
        json={"node_type": "issue", "node_id": issues[0].id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "continuity_graph_too_large",
        "limit": 1,
    }
@pytest.mark.asyncio
async def test_selected_member_collection_is_bounded(
    auth_client: AsyncClient,
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selected-member rows beyond their cap fail before rule evaluation.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.
        monkeypatch: Pytest fixture used to reduce the production cap for this regression.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="selected-limit-source", issue_count=2
    )
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="selected-limit-target", issue_count=1
    )
    source_group = await _make_group(
        async_db,
        user_id=user.id,
        suffix="selected-limit",
        issue_ids=[issue.id for issue in source_issues],
    )
    rule = _rule(
        user_id=user.id,
        source_type="crossover",
        source_id=source_group.id,
        target_type="issue",
        target_id=target_issues[0].id,
        satisfaction_type="selected_members_read",
    )
    rule.selected_members = [
        ContinuityRuleSelectedMember(issue_id=issue.id) for issue in source_issues
    ]
    async_db.add(rule)
    await async_db.commit()
    monkeypatch.setattr(readiness, "MAX_GRAPH_SELECTED_MEMBERS", 1)

    response = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "continuity_graph_too_large",
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_converged_gate_blocks_until_all_targets_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A converged rule stays blocked while any target is unread, then clears.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-source", issue_count=1
    )
    branch_a_thread, branch_a_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-a", issue_count=1
    )
    branch_b_thread, branch_b_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-b", issue_count=1
    )
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-target", issue_count=1
    )
    async_db.add(
        _rule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=target_issues[0].id,
            satisfaction_type="converged",
            convergence_targets=[
                {"type": "issue", "id": branch_a_issues[0].id},
                {"type": "issue", "id": branch_b_issues[0].id},
            ],
        )
    )
    await async_db.commit()

    blocked = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["is_readable"] is False
    blocker = blocked.json()["blockers"][0]
    assert blocker["satisfaction_type"] == "converged"
    assert set(blocker["causing_issue_ids"]) == {branch_a_issues[0].id, branch_b_issues[0].id}

    branch_a_issues[0].status = "read"
    branch_b_issues[0].status = "read"
    await async_db.commit()

    ready = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert ready.status_code == 200
    assert ready.json()["is_readable"] is True
    assert ready.json()["blockers"] == []


@pytest.mark.asyncio
async def test_converged_gate_with_crossover_target_blocks_until_members_read(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A converged rule keyed on a crossover stays blocked until its members read.

    Args:
        auth_client: Authenticated API client fixture.
        async_db: Async database session fixture.

    Returns:
        None.
    """
    user = await get_or_create_user_async(async_db)
    source_thread, source_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-x-source", issue_count=1
    )
    branch_thread, branch_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-x-branch", issue_count=2
    )
    _target_thread, target_issues = await _make_thread_with_issues(
        async_db, user_id=user.id, suffix="converge-x-target", issue_count=1
    )
    crossover = await _make_group(
        async_db,
        user_id=user.id,
        suffix="converge-x",
        issue_ids=[branch_issues[0].id, branch_issues[1].id],
    )
    async_db.add(
        _rule(
            user_id=user.id,
            source_type="issue",
            source_id=source_issues[0].id,
            target_type="issue",
            target_id=target_issues[0].id,
            satisfaction_type="converged",
            convergence_targets=[{"type": "crossover", "id": crossover.id}],
        )
    )
    await async_db.commit()

    blocked = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["is_readable"] is False
    blocker = blocked.json()["blockers"][0]
    assert blocker["satisfaction_type"] == "converged"
    assert set(blocker["causing_member_issue_ids"]) == {branch_issues[0].id, branch_issues[1].id}

    branch_issues[0].status = "read"
    branch_issues[1].status = "read"
    await async_db.commit()

    ready = await auth_client.post(
        "/api/v1/continuity/readiness",
        json={"node_type": "issue", "node_id": target_issues[0].id},
    )
    assert ready.status_code == 200
    assert ready.json()["is_readable"] is True
    assert ready.json()["blockers"] == []
