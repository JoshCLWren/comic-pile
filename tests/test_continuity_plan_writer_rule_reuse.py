"""Regression coverage for equivalent standalone rule reuse by Reading Plans."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.issue import Issue
from app.models.thread import Thread
from app.schemas.continuity_plan import ContinuityPlanNode
from app.services.continuity_plan_writer import replace_compiled_rules
from tests.conftest import get_or_create_user_async


async def _make_issue(db: AsyncSession, *, user_id: int, suffix: str) -> Issue:
    """Create one owned issue for writer-rule reuse tests."""
    thread = Thread(
        title=f"Rule reuse {suffix}",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    db.add(issue)
    await db.flush()
    return issue


def _nodes(source: Issue, target: Issue) -> list[ContinuityPlanNode]:
    """Build the two-node strict plan used by these tests."""
    return [
        ContinuityPlanNode(
            id=f"issue-{source.id}",
            node_type="issue",
            ref_id=source.id,
            lane_id="main",
            position=0,
            convergence_gate=[],
        ),
        ContinuityPlanNode(
            id=f"issue-{target.id}",
            node_type="issue",
            ref_id=target.id,
            lane_id="main",
            position=1,
            convergence_gate=[],
        ),
    ]


async def _plan(db: AsyncSession, *, user_id: int, name: str) -> ContinuityPlan:
    """Create one empty persisted plan so compiled rules have a stable owner marker."""
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[],
    )
    db.add(plan)
    await db.flush()
    return plan


@pytest.mark.asyncio
async def test_equivalent_standalone_item_read_rule_is_reused_without_reownership(
    async_db: AsyncSession,
) -> None:
    """A standalone item-read edge satisfies a strict plan without provenance loss."""
    user = await get_or_create_user_async(async_db)
    source = await _make_issue(async_db, user_id=user.id, suffix="source")
    target = await _make_issue(async_db, user_id=user.id, suffix="target")
    standalone = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=source.id,
        target_type="issue",
        target_id=target.id,
        satisfaction_type="item_read",
        note="Genuine standalone prerequisite",
    )
    async_db.add(standalone)
    await async_db.flush()
    standalone_id = standalone.id
    original_note = standalone.note

    plan = await _plan(async_db, user_id=user.id, name="Strict plan")
    nodes = _nodes(source, target)
    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await async_db.flush()

    rows = list(
        (
            await async_db.execute(
                select(ContinuityRule).where(
                    ContinuityRule.user_id == user.id,
                    ContinuityRule.source_id == source.id,
                    ContinuityRule.target_id == target.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].id == standalone_id
    assert rows[0].note == original_note
    assert rows[0].legacy_dependency_id is None

    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await async_db.flush()
    surviving = await async_db.get(ContinuityRule, standalone_id)
    assert surviving is not None
    assert surviving.note == original_note


@pytest.mark.asyncio
async def test_rule_owned_by_another_reading_plan_still_conflicts(
    async_db: AsyncSession,
) -> None:
    """Equivalent edges owned by another Reading Plan retain the stable conflict."""
    user = await get_or_create_user_async(async_db)
    source = await _make_issue(async_db, user_id=user.id, suffix="plan-a-source")
    target = await _make_issue(async_db, user_id=user.id, suffix="plan-a-target")
    nodes = _nodes(source, target)

    first = await _plan(async_db, user_id=user.id, name="First plan")
    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=first,
        nodes=nodes,
        ordering_mode="strict_sequential",
    )
    await async_db.flush()

    second = await _plan(async_db, user_id=user.id, name="Second plan")
    with pytest.raises(HTTPException) as captured:
        await replace_compiled_rules(
            async_db,
            user_id=user.id,
            plan=second,
            nodes=nodes,
            ordering_mode="strict_sequential",
        )

    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "plan_rule_conflict"


@pytest.mark.asyncio
async def test_non_equivalent_same_edge_rule_still_conflicts(
    async_db: AsyncSession,
) -> None:
    """A same-edge checkpoint cannot be silently reused as strict item-read order."""
    user = await get_or_create_user_async(async_db)
    source = await _make_issue(async_db, user_id=user.id, suffix="checkpoint-source")
    target = await _make_issue(async_db, user_id=user.id, suffix="checkpoint-target")
    async_db.add(
        ContinuityRule(
            user_id=user.id,
            source_type="issue",
            source_id=source.id,
            target_type="issue",
            target_id=target.id,
            satisfaction_type="checkpoint",
            checkpoint_issue_id=source.id,
            note="Standalone checkpoint",
        )
    )
    await async_db.flush()

    plan = await _plan(async_db, user_id=user.id, name="Strict plan")
    with pytest.raises(HTTPException) as captured:
        await replace_compiled_rules(
            async_db,
            user_id=user.id,
            plan=plan,
            nodes=_nodes(source, target),
            ordering_mode="strict_sequential",
        )

    assert captured.value.status_code == 409
    assert captured.value.detail["code"] == "plan_rule_conflict"
