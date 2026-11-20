"""Contract tests for docs/roll-eligibility-contract.md (Josh, 2026-10-12).

These PostgreSQL tests pin the authoritative Roll eligibility contract:
saving an unchanged strict plan diffs nothing, CBL adjacency / series
changes / plan membership never create blockers on their own, and explicit
checkpoint metadata can never recreate retired list-chain adjacency edges.
They also cover the three list-chain guards (legacy migration scripts, the
canonical backfill migration, and stale nodes_json convergence flags).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_rule import ContinuityRule
from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.canonical_backfill import abort_on_retired_list_chain_rules
from app.services.continuity_plan_writer import plan_rule_marker, replace_compiled_rules
from app.services.list_chain_guard import (
    assert_no_same_thread_pairs,
    partition_retired_list_chain_pairs,
)
from app.services.strict_plan_constraints import IssueThreadIndex
from tests.conftest import get_or_create_user_async
from tests.test_roll_cutover_migration import (
    _clean,
    _sync_connection,
    _thread_with_issues,
    _user,
)
from tests.test_strict_plan_enforcement import (
    _compiled_pairs,
    _make_series,
    _nodes,
    _plan_dependency_snapshot,
    _plan_payload,
    _plan_rule_snapshot,
    _roll_ids,
    _write_payload_from_get,
)


async def _rule_row_snapshot(
    db: AsyncSession, *, user_id: int, plan_id: int
) -> list[tuple[int, str, int, str, int, str, int | None]]:
    """Return durable plan-owned rule rows including ids (churn detection)."""
    rules = (
        await db.execute(
            select(ContinuityRule)
            .where(
                ContinuityRule.user_id == user_id,
                ContinuityRule.note == plan_rule_marker(plan_id),
            )
            .order_by(ContinuityRule.id)
        )
    ).scalars().all()
    return [
        (
            rule.id,
            rule.source_type,
            rule.source_id,
            rule.target_type,
            rule.target_id,
            rule.satisfaction_type,
            rule.checkpoint_issue_id,
        )
        for rule in rules
    ]


@pytest.mark.asyncio
async def test_unchanged_strict_save_produces_zero_rule_and_dependency_diff(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Contract: saving an unchanged strict plan changes nothing.

    Rule ids, rule identities, and plan-linked Dependencies are all compared
    so delete/recreate churn (identical values, new ids) still fails the diff.
    """
    user = await get_or_create_user_async(async_db)
    lead, lead_issues = await _make_series(
        async_db, user_id=user.id, title="Contract lead", numbers=["1", "2"], queue_position=1
    )
    follow, follow_issues = await _make_series(
        async_db, user_id=user.id, title="Contract follow", numbers=["1", "2"], queue_position=2
    )
    await async_db.commit()

    payload = _plan_payload(
        "Contract unchanged",
        lead_issues + follow_issues,
        checkpoint_ids={lead_issues[-1].id},
    )
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    before_rules = await _rule_row_snapshot(async_db, user_id=user.id, plan_id=plan_id)
    before_identities = await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id)
    before_deps = await _plan_dependency_snapshot(async_db, plan_id=plan_id)
    before_roll = await _roll_ids(user.id, async_db)
    assert before_identities == {
        (lead_issues[-1].id, follow_issues[0].id, "checkpoint", lead_issues[-1].id),
    }
    assert follow.id not in before_roll

    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert fetched.status_code == 200, fetched.text
    saved = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}",
        json=_write_payload_from_get(fetched.json()),
    )
    assert saved.status_code == 200, saved.text

    assert await _rule_row_snapshot(async_db, user_id=user.id, plan_id=plan_id) == before_rules
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id) == (
        before_identities
    )
    assert await _plan_dependency_snapshot(async_db, plan_id=plan_id) == before_deps
    assert await _roll_ids(user.id, async_db) == before_roll


@pytest.mark.asyncio
async def test_cbl_adjacency_series_change_and_membership_create_no_blockers(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Contract: adjacency, series changes, and membership gate nothing alone.

    Interleaved CBL order across three series compiles zero hard edges, and
    applying a reordered custom CBL (series changes plus membership churn)
    still adds none — only explicit checkpoints may block Roll.
    """
    user = await get_or_create_user_async(async_db)
    series_issues: list[list[Issue]] = []
    threads: list[Thread] = []
    for offset, title in enumerate(("Adjacency A", "Adjacency B", "Adjacency C"), start=1):
        thread, issues = await _make_series(
            async_db, user_id=user.id, title=title, numbers=["1", "2"], queue_position=offset
        )
        threads.append(thread)
        series_issues.append(issues)
    await async_db.commit()

    interleaved = [
        series_issues[0][0],
        series_issues[1][0],
        series_issues[2][0],
        series_issues[0][1],
        series_issues[1][1],
        series_issues[2][1],
    ]
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload("Contract adjacency", interleaved),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == set()
    assert await _plan_dependency_snapshot(async_db, plan_id=plan_id) == set()
    roll_ids = await _roll_ids(user.id, async_db)
    for thread in threads:
        assert thread.id in roll_ids

    # Apply a reordered custom CBL onto the plan: series membership changes
    # and new adjacency are still not blockers.
    reordered_ids = [
        series_issues[2][0].id,
        series_issues[0][0].id,
        series_issues[0][1].id,
        series_issues[2][1].id,
    ]
    custom = await auth_client.post(
        "/api/v1/custom-cbls",
        json={"name": "Contract reorder", "issue_ids": reordered_ids},
    )
    assert custom.status_code == 201, custom.text
    fetched = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    applied = await auth_client.post(
        f"/api/v1/custom-cbls/{custom.json()['id']}/reading-plans/{plan_id}:apply",
        json={"expected_updated_at": fetched.json()["updated_at"]},
    )
    assert applied.status_code == 200, applied.text
    assert await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id) == set()
    assert await _plan_dependency_snapshot(async_db, plan_id=plan_id) == set()
    roll_after = await _roll_ids(user.id, async_db)
    for thread in threads:
        assert thread.id in roll_after


@pytest.mark.asyncio
async def test_checkpoint_metadata_does_not_recreate_adjacency_edges(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Contract: is_checkpoint never becomes adjacency; explicit targets stick.

    A checkpoint with an explicit ``checkpoint_target_ref_id`` keeps blocking
    that exact issue across a reorder, never redirects to the new neighbor,
    and drops rather than retargets when its target leaves the plan.
    """
    user = await get_or_create_user_async(async_db)
    _a, a_issues = await _make_series(
        async_db, user_id=user.id, title="Checkpoint A", numbers=["1", "2"], queue_position=1
    )
    _b, b_issues = await _make_series(
        async_db, user_id=user.id, title="Checkpoint B", numbers=["1"], queue_position=2
    )
    _c, c_issues = await _make_series(
        async_db, user_id=user.id, title="Checkpoint C", numbers=["1"], queue_position=3
    )
    await async_db.commit()

    def payload(order: list[Issue], *, target_ref: int | None) -> dict[str, object]:
        return {
            "name": "Checkpoint targeting",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": [
                {
                    "id": f"issue-{issue.id}",
                    "node_type": "issue",
                    "ref_id": issue.id,
                    "lane_id": "main",
                    "position": position,
                    "is_checkpoint": issue is a_issues[-1],
                    "checkpoint_target_ref_id": (
                        target_ref if issue is a_issues[-1] else None
                    ),
                    "convergence_gate": None,
                }
                for position, issue in enumerate(order)
            ],
        }

    initial_order = [a_issues[0], a_issues[1], b_issues[0], c_issues[0]]
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=payload(initial_order, target_ref=b_issues[0].id),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    expected_edge = (a_issues[-1].id, b_issues[0].id, "checkpoint", a_issues[-1].id)
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id) == {
        expected_edge
    }

    # Reorder so a different series follows the checkpoint node: the explicit
    # target must not redirect to the new adjacent entry.
    reordered = [a_issues[0], a_issues[1], c_issues[0], b_issues[0]]
    saved = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}",
        json=payload(reordered, target_ref=b_issues[0].id),
    )
    assert saved.status_code == 200, saved.text
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id) == {
        expected_edge
    }
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id)
    assert (a_issues[-1].id, c_issues[0].id) not in compiled

    # Remove the target from the plan: the checkpoint drops instead of
    # retargeting whatever entry now follows it.
    dropped = [a_issues[0], a_issues[1], c_issues[0]]
    saved = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_id}",
        json=payload(dropped, target_ref=b_issues[0].id),
    )
    assert saved.status_code == 200, saved.text
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id) == set()
    compiled = await _compiled_pairs(async_db, user_id=user.id, plan_id=plan_id)
    assert (a_issues[-1].id, c_issues[0].id) not in compiled


async def _make_plan(
    db: AsyncSession, *, user_id: int, nodes: list
) -> ContinuityPlan:
    """Create a bare strict plan row for direct writer calls."""
    plan = ContinuityPlan(
        user_id=user_id,
        name="Guard plan",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Main", "order": 0}],
        nodes_json=[node.model_dump() for node in nodes],
    )
    db.add(plan)
    await db.flush()
    return plan


@pytest.mark.asyncio
async def test_legacy_migration_guard_rejects_same_thread_pairs(
    async_db: AsyncSession,
) -> None:
    """Guard 1: migration pair selections can never include same-thread edges."""
    index = {
        101: IssueThreadIndex(1, 1, True),
        102: IssueThreadIndex(1, 2, False),
        201: IssueThreadIndex(2, 1, True),
    }
    with pytest.raises(ValueError, match="same-thread item_read"):
        assert_no_same_thread_pairs([(101, 102)], index)
    assert_no_same_thread_pairs([(102, 201)], index)

    kept, retired = partition_retired_list_chain_pairs(
        [(101, 102), (102, 201), (101, 999)], index
    )
    assert kept == [(102, 201)]
    assert retired == [(101, 102), (101, 999)]

    # End-to-end through the writer extras path used by held migrations:
    # same-thread extras are never compiled into plan-owned rules.
    user = await get_or_create_user_async(async_db)
    _thread, issues = await _make_series(
        async_db, user_id=user.id, title="Guard series", numbers=["1", "2"], queue_position=1
    )
    _other, other_issues = await _make_series(
        async_db, user_id=user.id, title="Guard other", numbers=["1"], queue_position=2
    )
    await async_db.commit()
    nodes = _nodes(issues + other_issues)
    plan = await _make_plan(async_db, user_id=user.id, nodes=nodes)
    await replace_compiled_rules(
        async_db,
        user_id=user.id,
        plan=plan,
        nodes=nodes,
        ordering_mode="strict_sequential",
        extra_item_read_pairs=[
            (issues[0].id, issues[1].id),
            (issues[1].id, other_issues[0].id),
        ],
    )
    await async_db.commit()
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan.id) == {
        (issues[1].id, other_issues[0].id, "item_read", None),
    }


@pytest.mark.asyncio
async def test_backfill_guard_aborts_on_retired_list_chain_rules(
    async_db_committed: AsyncSession,
) -> None:
    """Guard 2: the legacy backfill aborts before recreating list chains."""
    db = async_db_committed
    await _clean(db)
    try:
        user = await _user(db, "list-chain-guard-user")
        _thread, (source_1, source_2) = await _thread_with_issues(
            db, user.id, "Chain Source", ["1", "2"]
        )
        db.add(
            ContinuityRule(
                user_id=user.id,
                source_type="issue",
                source_id=source_1.id,
                target_type="issue",
                target_id=source_2.id,
                satisfaction_type="item_read",
                note="continuity-plan:1",
            )
        )
        await db.commit()

        conn = _sync_connection()
        try:
            with pytest.raises(RuntimeError, match="retired generated list-chain"):
                abort_on_retired_list_chain_rules(conn)
        finally:
            conn.close()

        rule_row = (
            await db.execute(
                select(ContinuityRule).where(ContinuityRule.user_id == user.id)
            )
        ).scalars().one()
        await db.delete(rule_row)
        await db.commit()
        conn = _sync_connection()
        try:
            abort_on_retired_list_chain_rules(conn)
        finally:
            conn.close()
    finally:
        await _clean(db)


@pytest.mark.asyncio
async def test_stale_convergence_nodes_cannot_recreate_list_chain_edges(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Guard 3: stale nodes_json convergence flags recreate no chain edges.

    A convergence gate pointing at the node's own natural series predecessor
    is list-chain geometry in disguise and compiles nothing; a genuine
    cross-series convergence gate still compiles normally.
    """
    user = await get_or_create_user_async(async_db)
    _a, a_issues = await _make_series(
        async_db, user_id=user.id, title="Convergence A", numbers=["1", "2"], queue_position=1
    )
    _b, b_issues = await _make_series(
        async_db, user_id=user.id, title="Convergence B", numbers=["1", "2"], queue_position=2
    )
    third, c_issues = await _make_series(
        async_db, user_id=user.id, title="Convergence C", numbers=["1"], queue_position=3
    )
    now = datetime.now(UTC)
    await async_db.commit()

    def issue_node(issue: Issue, position: int, gate_to: Issue | None) -> dict[str, object]:
        gate: list[dict[str, str]] = (
            [{"node_type": "issue", "node_id": f"issue-{gate_to.id}"}]
            if gate_to is not None
            else []
        )
        return {
            "id": f"issue-{issue.id}",
            "node_type": "issue",
            "ref_id": issue.id,
            "lane_id": "main",
            "position": position,
            "is_checkpoint": False,
            "convergence_gate": gate,
        }

    nodes = [
        issue_node(a_issues[0], 0, None),
        issue_node(a_issues[1], 1, a_issues[0]),  # stale: own predecessor
        issue_node(b_issues[0], 2, None),
        issue_node(b_issues[1], 3, None),
        issue_node(c_issues[0], 4, b_issues[0]),  # genuine cross-series gate
    ]
    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json={
            "name": "Stale convergence",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Main", "order": 0}],
            "nodes": nodes,
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    rules = await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_id)
    # The stale same-series convergence flag compiled no edge for A #2.
    assert (a_issues[0].id, a_issues[1].id, "converged", None) not in rules
    assert not any(
        target == a_issues[1].id for _source, target, _satisfaction, _checkpoint in rules
    )
    leftover = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == a_issues[0].id,
                Dependency.target_issue_id == a_issues[1].id,
            )
        )
    ).scalar_one_or_none()
    assert leftover is None

    # The genuine cross-series convergence gate still compiles and blocks.
    assert (c_issues[0].id, c_issues[0].id, "converged", None) in rules
    gate_edge = (
        await async_db.execute(
            select(Dependency).where(
                Dependency.source_issue_id == b_issues[0].id,
                Dependency.target_issue_id == c_issues[0].id,
            )
        )
    ).scalar_one_or_none()
    assert gate_edge is not None
    roll_ids = await _roll_ids(user.id, async_db)
    assert third.id not in roll_ids
    b_issues[0].status = "read"
    b_issues[0].read_at = now
    _b.next_unread_issue_id = b_issues[1].id
    _b.issues_remaining = 1
    await async_db.flush()
    assert third.id in await _roll_ids(user.id, async_db)


@pytest.mark.asyncio
async def test_overlapping_strict_plans_preserve_each_others_checkpoint_dependencies(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Contract: overlapping strict plans never clobber each other's hard edges.

    Two strict plans share issues; each carries explicit checkpoint rules.
    Re-saving or editing one plan must leave the other plan's rules and hard
    Dependencies untouched, and read state on the shared issues satisfies
    both plans' blockers at once.
    """
    user = await get_or_create_user_async(async_db)
    _lead, lead_issues = await _make_series(
        async_db, user_id=user.id, title="Overlap lead", numbers=["1", "2"], queue_position=1
    )
    follow, follow_issues = await _make_series(
        async_db, user_id=user.id, title="Overlap follow", numbers=["1"], queue_position=2
    )
    mid, mid_issues = await _make_series(
        async_db, user_id=user.id, title="Overlap mid", numbers=["1"], queue_position=3
    )
    await async_db.commit()

    plan_a_issues = lead_issues + follow_issues
    created_a = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            "Overlap A", plan_a_issues, checkpoint_ids={lead_issues[-1].id}
        ),
    )
    assert created_a.status_code == 201, created_a.text
    plan_a_id = created_a.json()["id"]

    plan_b_issues = lead_issues + mid_issues
    created_b = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_plan_payload(
            "Overlap B", plan_b_issues, checkpoint_ids={lead_issues[-1].id}
        ),
    )
    assert created_b.status_code == 201, created_b.text
    plan_b_id = created_b.json()["id"]

    a_edge = (lead_issues[-1].id, follow_issues[0].id, "checkpoint", lead_issues[-1].id)
    b_edge = (lead_issues[-1].id, mid_issues[0].id, "checkpoint", lead_issues[-1].id)
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_a_id) == {
        a_edge
    }
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_b_id) == {
        b_edge
    }
    before_b_deps = await _plan_dependency_snapshot(async_db, plan_id=plan_b_id)
    roll_ids = await _roll_ids(user.id, async_db)
    assert follow.id not in roll_ids
    assert mid.id not in roll_ids

    # Re-saving plan A unchanged must not churn plan B's rules or edges.
    fetched_a = await auth_client.get(f"/api/v1/continuity-plans/{plan_a_id}")
    assert fetched_a.status_code == 200, fetched_a.text
    saved_a = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_a_id}",
        json=_write_payload_from_get(fetched_a.json()),
    )
    assert saved_a.status_code == 200, saved_a.text
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_b_id) == {
        b_edge
    }
    assert await _plan_dependency_snapshot(async_db, plan_id=plan_b_id) == before_b_deps

    # Editing plan A (dropping its segue target) retires only plan A's
    # checkpoint; plan B keeps its hard Dependencies on the shared issues.
    edited_a = await auth_client.put(
        f"/api/v1/continuity-plans/{plan_a_id}",
        json=_plan_payload(
            "Overlap A", lead_issues, checkpoint_ids={lead_issues[-1].id}
        ),
    )
    assert edited_a.status_code == 200, edited_a.text
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_a_id) == set()
    assert await _plan_rule_snapshot(async_db, user_id=user.id, plan_id=plan_b_id) == {
        b_edge
    }
    assert await _plan_dependency_snapshot(async_db, plan_id=plan_b_id) == before_b_deps
    roll_after_edit = await _roll_ids(user.id, async_db)
    assert mid.id not in roll_after_edit

    # Read state is shared: reading the lead issues lifts both plans' blockers.
    now = datetime.now(UTC)
    _lead.reading_progress = "completed"
    _lead.issues_remaining = 0
    _lead.next_unread_issue_id = None
    for issue in lead_issues:
        issue.status = "read"
        issue.read_at = now
    await async_db.flush()
    roll_final = await _roll_ids(user.id, async_db)
    assert follow.id in roll_final
    assert mid.id in roll_final
