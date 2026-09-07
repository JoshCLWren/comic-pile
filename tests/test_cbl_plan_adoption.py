"""Issue #2377: canonical CBL adoption mutates Reading Plans, not dependency groups."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.dependency_group import DependencyGroup
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.cbl_plan_adoption import (
    CBLPlanAdoptionError,
    CBLReviewedSource,
    commit_existing_cbl_entries_to_reading_plan,
)
from app.services.cbl_reconciliation import preview_cbl_adoption
from tests.conftest import get_or_create_user_async


async def _seed_existing_source(async_db: AsyncSession, *, user_id: int) -> tuple[int, Issue]:
    """Create one owned canonical issue and one CBL entry resolving to it."""
    thread = Thread(
        title="B.P.R.D.",
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="not_started",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()

    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=f"4000-{issue.id}",
        metadata_json={},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
        )
    )

    source = CBLSource(
        repository="JoshCLWren/CBL-ReadingLists",
        revision_sha="sha-2377",
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Dark Horse/BPRD/Next Phase.cbl",
        name="B.P.R.D. Next Phase",
        declared_issue_count=1,
        content_hash="hash-2377",
        revision_sha="sha-2377",
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=7,
            series_name="B.P.R.D.",
            issue_number="1",
            external_issue_identity_id=identity.id,
        )
    )
    await async_db.flush()
    return source_list.id, issue


async def _review(
    async_db: AsyncSession, *, user_id: int, list_id: int
) -> tuple[CBLReviewedSource, list[dict[str, object]], tuple[int, ...]]:
    """Capture the exact source fingerprint and entry facts a reader reviewed."""
    report, plan = await preview_cbl_adoption(async_db, user_id=user_id, list_id=list_id)
    assert report.source_list_id is not None
    assert report.source_repository is not None
    assert report.source_path is not None
    assert report.content_hash is not None
    assert report.revision_sha is not None
    return (
        CBLReviewedSource(
            source_list_id=report.source_list_id,
            source_repository=report.source_repository,
            source_path=report.source_path,
            content_hash=report.content_hash,
            revision_sha=report.revision_sha,
        ),
        [dict(entry) for entry in plan.entries],
        plan.final_adopted_order,
    )


@pytest.mark.asyncio
async def test_existing_cbl_commit_updates_same_plan_and_is_idempotent(
    async_db: AsyncSession,
) -> None:
    """Existing comics become plan nodes with provenance and replay creates nothing."""
    user = await get_or_create_user_async(async_db)
    list_id, issue = await _seed_existing_source(async_db, user_id=user.id)
    plan = ContinuityPlan(
        user_id=user.id,
        name="B.P.R.D.",
        ordering_mode="informational",
        lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
        nodes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    source, reviewed_entries, reviewed_order = await _review(
        async_db, user_id=user.id, list_id=list_id
    )

    before_groups = await async_db.scalar(select(func.count()).select_from(DependencyGroup))
    first = await commit_existing_cbl_entries_to_reading_plan(
        async_db,
        user_id=user.id,
        plan_id=plan.id,
        list_id=list_id,
        reviewed_source=source,
        reviewed_entries=reviewed_entries,
        reviewed_final_positions=reviewed_order,
        series_decisions={},
        entry_decisions={},
    )
    await async_db.refresh(plan)

    assert first.added_issue_ids == (issue.id,)
    assert first.idempotent_replay is False
    assert len(plan.nodes_json) == 1
    node = plan.nodes_json[0]
    assert node["ref_id"] == issue.id
    assert node["source_paths"] == [source.source_path]
    assert node["source_cbl_placements"] == [
        {"source_path": source.source_path, "position": 7}
    ]
    assert plan.ordering_mode == "informational"
    assert await async_db.scalar(select(func.count()).select_from(DependencyGroup)) == before_groups

    second = await commit_existing_cbl_entries_to_reading_plan(
        async_db,
        user_id=user.id,
        plan_id=plan.id,
        list_id=list_id,
        reviewed_source=source,
        reviewed_entries=reviewed_entries,
        reviewed_final_positions=reviewed_order,
        series_decisions={},
        entry_decisions={},
    )
    await async_db.refresh(plan)
    assert second.added_issue_ids == ()
    assert second.reused_issue_ids == (issue.id,)
    assert second.idempotent_replay is True
    assert len(plan.nodes_json) == 1


@pytest.mark.asyncio
async def test_strict_plan_fails_before_mutation(
    async_db: AsyncSession,
) -> None:
    """This slice refuses to bypass the router-owned strict-plan compiler."""
    user = await get_or_create_user_async(async_db)
    list_id, _issue = await _seed_existing_source(async_db, user_id=user.id)
    plan = ContinuityPlan(
        user_id=user.id,
        name="Strict B.P.R.D.",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
        nodes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    source, reviewed_entries, reviewed_order = await _review(
        async_db, user_id=user.id, list_id=list_id
    )

    with pytest.raises(CBLPlanAdoptionError) as caught:
        await commit_existing_cbl_entries_to_reading_plan(
            async_db,
            user_id=user.id,
            plan_id=plan.id,
            list_id=list_id,
            reviewed_source=source,
            reviewed_entries=reviewed_entries,
            reviewed_final_positions=reviewed_order,
            series_decisions={},
            entry_decisions={},
        )

    assert caught.value.code == "strict_plan_writer_not_extracted"
    await async_db.rollback()
    fresh = await async_db.get(ContinuityPlan, plan.id)
    assert fresh is not None
    assert fresh.nodes_json == []
