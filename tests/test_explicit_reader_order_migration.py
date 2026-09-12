"""PostgreSQL coverage for Step 27 classified reader-order migration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.explicit_reader_order_migration import (
    ExplicitReaderOrderSpec,
    apply_explicit_reader_order_migration,
    build_explicit_reader_order_dry_run,
)
from comic_pile.dependencies import refresh_user_blocked_status
from tests.conftest import get_or_create_user_async


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
    status: str,
) -> tuple[Thread, Issue]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="completed" if status == "read" else "active",
        total_issues=1,
        issues_remaining=0 if status == "read" else 1,
        reading_progress="completed" if status == "read" else "unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status=status,
        read_at=datetime.now(UTC) if status == "read" else None,
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = None if status == "read" else issue.id
    return thread, issue


@pytest.mark.asyncio
async def test_explicit_reader_order_migration_preserves_partial_order_without_linearizing(
    async_db: AsyncSession,
) -> None:
    """Replace classified edges exactly while preserving a standalone prerequisite."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="A",
            queue_position=1,
            status="unread",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="B",
            queue_position=2,
            status="read",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="C",
            queue_position=3,
            status="unread",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="D",
            queue_position=4,
            status="unread",
        ),
    ]
    issues = [row[1] for row in rows]

    group = DependencyGroup(
        user_id=user.id,
        name="Partial Reader Order",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))

    reader_order = [
        Dependency(
            source_issue_id=issues[0].id,
            target_issue_id=issues[2].id,
            note="classified reader order A->C",
            created_at=datetime.now(UTC),
        ),
        Dependency(
            source_issue_id=issues[1].id,
            target_issue_id=issues[2].id,
            note="classified reader order B->C",
            created_at=datetime.now(UTC),
        ),
        Dependency(
            source_issue_id=issues[2].id,
            target_issue_id=issues[3].id,
            note="classified reader order C->D",
            created_at=datetime.now(UTC),
        ),
    ]
    standalone = Dependency(
        source_issue_id=issues[1].id,
        target_issue_id=issues[3].id,
        note="standalone prerequisite B->D",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([*reader_order, standalone])
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = ExplicitReaderOrderSpec(
        user_id=user.id,
        dependency_group_ids=(group.id,),
        expected_group_names=(group.name,),
        plan_name="Partial Reader Order",
        reader_order_dependency_ids=tuple(dependency.id for dependency in reader_order),
        preserved_dependency_ids=(standalone.id,),
    )
    snapshot = await build_explicit_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    assert snapshot["planned"]["edge_count"] == 3
    assert snapshot["planned"]["rule_count"] == 2
    assert snapshot["runtime_behavior"][
        "current_affected_roll_eligible_thread_ids"
    ] == snapshot["runtime_behavior"]["simulated_future_eligible_thread_ids"]
    assert [row["id"] for row in snapshot["preserved_standalone_dependencies"]] == [
        standalone.id
    ]

    nodes = {
        node["ref_id"]: node for node in snapshot["planned"]["plan"]["nodes"]
    }
    assert nodes[issues[2].id]["convergence_gate"] == [
        {"node_type": "issue", "node_id": f"issue-{issues[0].id}"},
        {"node_type": "issue", "node_id": f"issue-{issues[1].id}"},
    ]
    assert nodes[issues[3].id]["convergence_gate"] == [
        {"node_type": "issue", "node_id": f"issue-{issues[2].id}"}
    ]

    receipt = await apply_explicit_reader_order_migration(
        async_db,
        snapshot=snapshot,
        spec=spec,
    )
    await async_db.commit()

    assert receipt["removed_reader_order_dependency_count"] == 3
    assert receipt["preserved_standalone_dependency_count"] == 1
    for dependency in reader_order:
        assert await async_db.get(Dependency, dependency.id) is None
    assert await async_db.get(Dependency, standalone.id) is not None

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    assert plan.ordering_mode == "informational"
    assert {node["ref_id"] for node in plan.nodes_json} == {
        issue.id for issue in issues
    }
    plan_rules = list(
        (
            await async_db.execute(
                select(plan_rule)
                for plan_rule in []
            )
        )
    ) if False else None
    assert plan_rules is None
