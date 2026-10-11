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


async def _rule_payload(source_id: int, target_id: int) -> dict:
    return {
        "source_type": "issue",
        "source_id": source_id,
        "target_type": "issue",
        "target_id": target_id,
        "satisfaction_type": "item_read",
        "selected_member_issue_ids": [],
    }


async def _edge_note(db: AsyncSession, source_id: int, target_id: int) -> str | None:
    return (
        await db.execute(
            select(Dependency.note).where(
                Dependency.source_issue_id == source_id,
                Dependency.target_issue_id == target_id,
            )
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_rule_create_compiles_canonical_edge(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """POSTing an item_read rule persists a canonical edge that blocks Roll."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Compiler Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Compiler Target", queue_position=2
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=await _rule_payload(source_issue.id, target_issue.id),
    )
    assert created.status_code == 201, created.text

    note = await _edge_note(async_db, source_issue.id, target_issue.id)
    assert note is not None and note.startswith("canonical:rule:")
    assert "cbl-order:" not in note

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked


@pytest.mark.asyncio
async def test_rule_delete_retires_compiled_edge(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Deleting a rule removes its compiled edge and unblocks the target."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Retire Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Retire Target", queue_position=2
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=await _rule_payload(source_issue.id, target_issue.id),
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    deleted = await auth_client.delete(f"/api/v1/continuity-rules/{rule_id}")
    assert deleted.status_code == 204, deleted.text

    assert await _edge_note(async_db, source_issue.id, target_issue.id) is None
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked


@pytest.mark.asyncio
async def test_rule_update_resyncs_compiled_edges(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Replacing a rule retires the old edge and compiles the new one."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Update Source", queue_position=1
    )
    old_target_thread, old_target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Old Target", queue_position=2
    )
    new_target_thread, new_target_issue = await _thread_issue(
        async_db, user_id=user.id, title="New Target", queue_position=3
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=await _rule_payload(source_issue.id, old_target_issue.id),
    )
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]

    updated = await auth_client.put(
        f"/api/v1/continuity-rules/{rule_id}",
        json=await _rule_payload(source_issue.id, new_target_issue.id),
    )
    assert updated.status_code == 200, updated.text

    assert await _edge_note(async_db, source_issue.id, old_target_issue.id) is None
    assert await _edge_note(async_db, source_issue.id, new_target_issue.id) is not None

    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert old_target_thread.id not in blocked
    assert new_target_thread.id in blocked


@pytest.mark.asyncio
async def test_shared_edge_survives_until_last_rule_deleted(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """An edge compiled from two rules is kept until both rules are gone."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Shared Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Shared Target", queue_position=2
    )
    await async_db.commit()

    first = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=await _rule_payload(source_issue.id, target_issue.id),
    )
    assert first.status_code == 201, first.text

    # A converged rule compiling to the same pair shares the edge. Created
    # directly because the API rejects self-targeting payloads.
    from app.models.continuity_rule import ContinuityRule

    second_rule = ContinuityRule(
        user_id=user.id,
        source_type="issue",
        source_id=target_issue.id,
        target_type="issue",
        target_id=target_issue.id,
        satisfaction_type="converged",
        convergence_targets=[{"type": "issue", "id": source_issue.id}],
    )
    async_db.add(second_rule)
    await async_db.commit()
    second_id = second_rule.id

    deleted_first = await auth_client.delete(f"/api/v1/continuity-rules/{first.json()['id']}")
    assert deleted_first.status_code == 204, deleted_first.text
    # The converged rule still intends the pair, so the edge survives.
    assert await _edge_note(async_db, source_issue.id, target_issue.id) is not None
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked

    deleted_second = await auth_client.delete(f"/api/v1/continuity-rules/{second_id}")
    assert deleted_second.status_code == 204, deleted_second.text
    assert await _edge_note(async_db, source_issue.id, target_issue.id) is None
    blocked_after = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id not in blocked_after


@pytest.mark.asyncio
async def test_rule_delete_never_removes_standalone_edge(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Deleting a rule keeps a standalone reader-created edge for the same pair."""
    user = await get_or_create_user_async(async_db)
    _source_thread, source_issue = await _thread_issue(
        async_db, user_id=user.id, title="Standalone Source", queue_position=1
    )
    target_thread, target_issue = await _thread_issue(
        async_db, user_id=user.id, title="Standalone Target", queue_position=2
    )
    async_db.add(
        Dependency(
            source_issue_id=source_issue.id,
            target_issue_id=target_issue.id,
            note="reader-created standalone",
        )
    )
    await async_db.commit()

    created = await auth_client.post(
        "/api/v1/continuity-rules/",
        json=await _rule_payload(source_issue.id, target_issue.id),
    )
    assert created.status_code == 201, created.text

    deleted = await auth_client.delete(f"/api/v1/continuity-rules/{created.json()['id']}")
    assert deleted.status_code == 204, deleted.text

    # The standalone edge (non-rule note) survives the rule deletion.
    assert (
        await _edge_note(async_db, source_issue.id, target_issue.id)
        == "reader-created standalone"
    )
    blocked = await _get_blocked_thread_ids_uncached(user.id, async_db)
    assert target_thread.id in blocked
