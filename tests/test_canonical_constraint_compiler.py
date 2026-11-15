"""Write-path compilation of ContinuityRules into canonical Dependencies (#2553).

Authoring a rule via the API compiles its hard semantics into canonical
Dependency edges in the same transaction; updating or deleting the rule syncs
the edges. The edge is the Roll authority; the rule remains the authoring
record.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dependency import Dependency
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanDependency
from app.models.thread import Thread
from comic_pile.dependencies import _get_blocked_thread_ids_uncached
from tests.conftest import get_or_create_user_async


async def _thread_issue(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> tuple[Thread, Issue]:
    thread = Thread(
        user_id=user_id,
        title=title,
        format="comic",
        queue_position=queue_position,
        status="active",
        total_issues=1,
        issues_remaining=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()
    thread.next_unread_issue_id = issue.id
    return thread, issue


async def _edge_note(db: AsyncSession, source_id: int, target_id: int) -> str | None:
    return (
        await db.execute(
            select(Dependency.note).where(
                Dependency.source_issue_id == source_id,
                Dependency.target_issue_id == target_id,
            )
        )
    ).scalar_one_or_none()


def _strict_plan_payload(
    issue_ids: list[int],
    *,
    name: str = "Compiler Plan",
    checkpoint_ids: set[int] | None = None,
) -> dict[str, object]:
    """Build a one-lane strict sequential plan payload."""
    flagged = checkpoint_ids or set()
    return {
        "name": name,
        "ordering_mode": "strict_sequential",
        "lanes": [{"id": "main", "name": "Main", "order": 0}],
        "nodes": [
            {
                "id": f"issue-{issue_id}",
                "node_type": "issue",
                "ref_id": issue_id,
                "lane_id": "main",
                "position": position,
                "is_checkpoint": issue_id in flagged,
                "convergence_gate": None,
            }
            for position, issue_id in enumerate(issue_ids)
        ],
    }


@pytest.mark.asyncio
async def test_plan_save_promotes_cbl_order_occupant_of_checkpoint_gate(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """A CBL checkpoint occupying an inert cbl-order pair promotes that pair."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Plan CBL Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Plan CBL Target", queue_position=2
    )
    source_id = source_issue.id
    target_id = target_issue.id
    async_db.add(
        Dependency(
            source_issue_id=source_id,
            target_issue_id=target_id,
            note="cbl-order:source:hash:plan",
        )
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_strict_plan_payload([source_id, target_id], checkpoint_ids={source_id}),
    )
    assert created.status_code == 201, created.text
    note = await _edge_note(async_db, source_id, target_id)
    assert note is not None and note.startswith("canonical:rule:")
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked


@pytest.mark.asyncio
async def test_plan_create_links_canonical_edges_for_provenance(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Live plan compilation inserts reading_plan_dependencies for compiled edges."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Provenance Source", queue_position=1
    )
    _target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Provenance Target", queue_position=2
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_strict_plan_payload(
            [source_issue.id, target_issue.id],
            name="Provenance",
            checkpoint_ids={source_issue.id},
        ),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    links = (
        await async_db.execute(
            select(ReadingPlanDependency).where(ReadingPlanDependency.plan_id == plan_id)
        )
    ).scalars().all()
    assert len(links) == 1
    note = await _edge_note(async_db, source_issue.id, target_issue.id)
    assert note is not None and note.startswith("canonical:rule:")


@pytest.mark.asyncio
async def test_unchanged_strict_resave_preserves_rule_identities(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Re-saving an unchanged strict plan preserves rule identities (zero churn).

    Contract: "Saving an unchanged plan changes nothing: issue identity,
    membership, hard Dependencies and Roll eligibility all stay the same."
    Rule IDs and Dependency notes must not churn on a no-op save.
    """
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Resave Source", queue_position=1
    )
    _target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Resave Target", queue_position=2
    )
    await async_db.commit()

    payload = _strict_plan_payload(
        [source_issue.id, target_issue.id],
        name="Resave",
        checkpoint_ids={source_issue.id},
    )
    created = await auth_client.post("/api/v1/continuity-plans/", json=payload)
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]
    first_note = await _edge_note(async_db, source_issue.id, target_issue.id)
    assert first_note is not None and first_note.startswith("canonical:rule:")

    updated = await auth_client.put(f"/api/v1/continuity-plans/{plan_id}", json=payload)
    assert updated.status_code == 200, updated.text
    second_note = await _edge_note(async_db, source_issue.id, target_issue.id)
    assert second_note is not None and second_note.startswith("canonical:rule:")
    assert second_note == first_note


@pytest.mark.asyncio
async def test_plan_delete_keeps_shared_canonical_edge(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Deleting a plan retires only unshared compiled edges (#2553 shared-pair)."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Shared Plan Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Shared Plan Target", queue_position=2
    )
    await async_db.commit()

    from app.models.continuity_rule import ContinuityRule
    from app.services.canonical_constraint_compiler import compile_rule_edges

    standalone = ContinuityRule(
        user_id=user.id, source_type="issue", source_id=source_issue.id,
        target_type="issue", target_id=target_issue.id, satisfaction_type="item_read",
    )
    async_db.add(standalone)
    await async_db.flush()
    await compile_rule_edges(async_db, standalone)
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-plans/",
        json=_strict_plan_payload([source_issue.id, target_issue.id], name="Shared Plan"),
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    deleted = await auth_client.delete(f"/api/v1/continuity-plans/{plan_id}")
    assert deleted.status_code == 204, deleted.text

    assert await _edge_note(async_db, source_issue.id, target_issue.id) is not None
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked


@pytest.mark.asyncio
async def test_plan_rollback_keeps_edge_shared_with_standalone_rule(
    async_db: AsyncSession,
) -> None:
    """BPRD/Ultimate rollback must not delete a pair another rule still compiles."""
    from app.models.continuity_rule import ContinuityRule
    from app.services.canonical_constraint_compiler import compile_rule_edges
    from app.services.migration_shared import retire_plan_compiled_edges

    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Rollback Shared Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Rollback Shared Target", queue_position=2
    )
    await async_db.commit()
    source_id = source_issue.id
    target_id = target_issue.id
    target_thread_id = target_thread.id

    standalone = ContinuityRule(
        user_id=user.id, source_type="issue", source_id=source_id,
        target_type="issue", target_id=target_id, satisfaction_type="item_read",
    )
    async_db.add(standalone)
    await async_db.flush()
    await compile_rule_edges(async_db, standalone)
    await async_db.commit()

    plan_rule = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=target_id,
        target_type="issue",
        target_id=target_id,
        satisfaction_type="converged",
        convergence_targets=[{"type": "issue", "id": source_id}],
        note="continuity-plan:1",
    )
    async_db.add(plan_rule)
    await async_db.flush()
    await compile_rule_edges(async_db, plan_rule)
    plan_rule_id = plan_rule.id
    await async_db.commit()

    refreshed = await _edge_note(async_db, source_id, target_id)
    assert refreshed == f"canonical:rule:{plan_rule_id}"

    await retire_plan_compiled_edges(async_db, rule_ids=[plan_rule_id])
    await async_db.commit()

    assert await _edge_note(async_db, source_id, target_id) is not None
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread_id in blocked
