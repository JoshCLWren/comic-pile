"""Integrated Reading Plan CBL golden path with missing materialization and replay."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.dependency_group import DependencyGroup
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from comic_pile.queue import get_roll_pool
from tests.conftest import get_or_create_user_async


async def _make_thread(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    queue_position: int,
) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=0,
        reading_progress="in_progress",
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    return thread


async def _add_issue(
    db: AsyncSession,
    *,
    thread: Thread,
    issue_number: str,
    position: int,
    read: bool,
) -> Issue:
    issue = Issue(
        thread_id=thread.id,
        issue_number=issue_number,
        position=position,
        status="read" if read else "unread",
        read_at=datetime.now(UTC) if read else None,
    )
    db.add(issue)
    await db.flush()
    thread.total_issues = (thread.total_issues or 0) + 1
    if not read:
        thread.issues_remaining = (thread.issues_remaining or 0) + 1
        if thread.next_unread_issue_id is None:
            thread.next_unread_issue_id = issue.id
    return issue


def _plan_node(issue: Issue, position: int) -> dict[str, object]:
    return {
        "id": f"issue-{issue.id}",
        "node_type": "issue",
        "ref_id": issue.id,
        "lane_id": "main",
        "position": position,
    }


@pytest.mark.asyncio
async def test_cbl_adoption_materializes_missing_replays_and_preserves_roll_boundary(
    auth_client: AsyncClient,
    async_db: AsyncSession,
) -> None:
    """Missing comics materialize once, replay stays idempotent, and groups stay inert."""
    user = await get_or_create_user_async(async_db)
    owned = await _make_thread(
        async_db,
        user_id=user.id,
        title="Golden Path Owned",
        queue_position=1,
    )
    owned_issue = await _add_issue(
        async_db,
        thread=owned,
        issue_number="1",
        position=1,
        read=True,
    )
    await async_db.commit()

    create = await auth_client.post(
        "/api/v1/continuity-plans/",
        json={
            "name": "Golden Path Plan",
            "ordering_mode": "strict_sequential",
            "lanes": [{"id": "main", "name": "Reading order", "order": 0}],
            "nodes": [_plan_node(owned_issue, 0)],
        },
    )
    assert create.status_code == 201, create.text
    plan_id = create.json()["id"]

    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists-golden-path",
        revision_sha="golden-rev",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Fixtures/Golden Path Mixed.cbl",
        name="Golden Path Mixed",
        declared_issue_count=2,
        content_hash="golden-content",
        revision_sha="golden-rev",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    owned_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-golden-owned",
        metadata_json={},
    )
    missing_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-golden-missing",
        metadata_json={"volume": {"name": "Golden Path Missing", "start_year": 2001}},
    )
    async_db.add_all([owned_identity, missing_identity])
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=owned_issue.id,
            external_identity_id=owned_identity.id,
            status="confirmed",
            evidence_source="golden-path",
        )
    )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Golden Path Owned",
            issue_number="1",
            external_issue_identity_id=owned_identity.id,
        )
    )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=2,
            series_name="Golden Path Missing",
            issue_number="1",
            volume_year=2001,
            external_issue_identity_id=missing_identity.id,
        )
    )
    await async_db.commit()

    groups_before = await async_db.scalar(
        select(func.count()).select_from(DependencyGroup).where(DependencyGroup.user_id == user.id)
    )
    issues_before = await async_db.scalar(select(func.count()).select_from(Issue))

    discovery = await auth_client.get("/api/v1/issue-identity/cbl-sources?q=Golden%20Path")
    assert discovery.status_code == 200, discovery.text
    assert source_list.id in [item["id"] for item in discovery.json()]

    preview_response = await auth_client.get(
        f"/api/v1/issue-identity/cbl/{source_list.id}/adoption-preview"
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["entries"][0]["adoption_class"] == "existing"
    assert preview["entries"][1]["adoption_class"] == "missing_importable"
    series_group_id = preview["entries"][1]["series_group_id"]

    assert series_group_id
    commit_payload = {
        "entry_decisions": {},
        "series_decisions": [
            {"series_name": "Golden Path Missing", "decision": "include"},
        ],
        "series_overrides": [],
        "content_hash": preview["source"]["content_hash"],
        "revision_sha": preview["source"]["revision_sha"],
    }
    commit = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/reading-plans/{plan_id}/adoption-commit",
        json=commit_payload,
    )
    assert commit.status_code == 200, commit.text
    committed = commit.json()
    assert committed["reused_positions"] == [1]
    assert committed["created_positions"] == [2]
    assert committed["unresolved_positions"] == []

    issues_after = await async_db.scalar(select(func.count()).select_from(Issue))
    assert issues_after == (issues_before or 0) + 1

    reload_after = await auth_client.get(f"/api/v1/continuity-plans/{plan_id}")
    assert reload_after.status_code == 200, reload_after.text
    reloaded = reload_after.json()
    assert len(reloaded["nodes"]) == 2
    assert reloaded["nodes"][0]["ref_id"] == owned_issue.id
    created_issue_id = reloaded["nodes"][1]["ref_id"]
    assert created_issue_id != owned_issue.id
    assert [
        placement["source_path"]
        for node in reloaded["nodes"]
        for placement in node.get("source_cbl_placements", [])
    ] == ["Fixtures/Golden Path Mixed.cbl"] * 2

    index = await auth_client.get("/api/v1/continuity-plans/")
    assert index.status_code == 200, index.text
    listed = next(item for item in index.json() if item["id"] == plan_id)
    assert listed["source_paths"] == ["Fixtures/Golden Path Mixed.cbl"]

    created_issue = await async_db.get(Issue, created_issue_id)
    assert created_issue is not None
    created_thread = await async_db.get(Thread, created_issue.thread_id)
    assert created_thread is not None
    assert created_thread.next_unread_issue_id == created_issue.id

    pool = await get_roll_pool(user.id, async_db)
    pool_ids = {thread.id for thread in pool}
    assert created_thread.id in pool_ids
    assert owned.id not in pool_ids or owned.next_unread_issue_id is None

    replay = await auth_client.post(
        f"/api/v1/cbl/{source_list.id}/reading-plans/{plan_id}/adoption-commit",
        json=commit_payload,
    )
    assert replay.status_code == 200, replay.text
    replayed = replay.json()
    assert replayed["created_positions"] == []
    assert replayed["reused_positions"] == [1, 2]
    assert len(replayed["nodes"]) == 2
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == issues_after

    groups_after = await async_db.scalar(
        select(func.count()).select_from(DependencyGroup).where(DependencyGroup.user_id == user.id)
    )
    assert groups_after == groups_before
