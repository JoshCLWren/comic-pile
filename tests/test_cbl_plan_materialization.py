"""Issue #2383: approved missing CBL comics become canonical Reading Plan issues."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup
from app.models.external_identity import ExternalIdentity, ThreadExternalSeriesMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.cbl_plan_adoption import (
    CBLReviewedSource,
    commit_existing_cbl_entries_to_reading_plan,
)
from app.services.cbl_reconciliation import preview_cbl_adoption
from app.services.continuity_plan_writer import plan_marker
from tests.conftest import get_or_create_user_async


async def _seed_missing_source(
    async_db: AsyncSession,
    *,
    series_external_id: str,
    issue_external_id: str,
    issue_number: str,
    series_name: str,
    source_path: str,
) -> tuple[int, CBLSourceEntry, ExternalIdentity]:
    """Create one source entry with stable identities but no canonical issue mapping."""
    series_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=series_external_id,
        metadata_json={},
    )
    issue_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id=issue_external_id,
        metadata_json={},
    )
    async_db.add_all([series_identity, issue_identity])
    await async_db.flush()

    source = CBLSource(
        repository=f"JoshCLWren/CBL-ReadingLists-{series_external_id}",
        revision_sha="a" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path=source_path,
        name=series_name,
        declared_issue_count=1,
        content_hash="b" * 64,
        revision_sha="a" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    entry = CBLSourceEntry(
        list_id=source_list.id,
        position=1,
        series_name=series_name,
        issue_number=issue_number,
        external_series_identity_id=series_identity.id,
        external_issue_identity_id=issue_identity.id,
    )
    async_db.add(entry)
    await async_db.flush()
    return source_list.id, entry, series_identity


async def _review_missing(
    async_db: AsyncSession,
    *,
    user_id: int,
    list_id: int,
    entry_id: int,
) -> tuple[CBLReviewedSource, list[dict[str, object]], tuple[int, ...], dict[str, bool]]:
    """Preview and explicitly opt into one missing source entry."""
    decisions = {str(entry_id): True}
    report, plan = await preview_cbl_adoption(
        async_db,
        user_id=user_id,
        list_id=list_id,
        entry_decisions=decisions,
    )
    assert report.source_list_id is not None
    assert report.source_repository is not None
    assert report.source_path is not None
    assert report.content_hash is not None
    assert report.revision_sha is not None
    assert plan.entries[0]["adoption_class"] == "missing_importable"
    assert plan.entries[0]["adopted"] is True
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
        decisions,
    )


@pytest.mark.asyncio
async def test_missing_cbl_issue_creates_canonical_thread_and_strict_plan_node(
    async_db: AsyncSession,
) -> None:
    """Approved missing material becomes one canonical issue and strict plan step."""
    user = await get_or_create_user_async(async_db)
    list_id, entry, _series_identity = await _seed_missing_source(
        async_db,
        series_external_id="bprd-universal-machine",
        issue_external_id="900001",
        issue_number="1",
        series_name="B.P.R.D.: The Universal Machine",
        source_path="Dark Horse/BPRD/Plague of Frogs Vol 3.cbl",
    )
    plan = ContinuityPlan(
        user_id=user.id,
        name="B.P.R.D.",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
        nodes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    source, reviewed_entries, reviewed_order, decisions = await _review_missing(
        async_db, user_id=user.id, list_id=list_id, entry_id=entry.id
    )
    before_groups = await async_db.scalar(select(func.count()).select_from(DependencyGroup))
    before_dependencies = await async_db.scalar(select(func.count()).select_from(Dependency))

    first = await commit_existing_cbl_entries_to_reading_plan(
        async_db,
        user_id=user.id,
        plan_id=plan.id,
        list_id=list_id,
        reviewed_source=source,
        reviewed_entries=reviewed_entries,
        reviewed_final_positions=reviewed_order,
        series_decisions={},
        entry_decisions=decisions,
    )
    await async_db.refresh(plan)

    assert len(first.created_issue_ids) == 1
    assert len(first.created_thread_ids) == 1
    assert first.added_issue_ids == first.created_issue_ids
    created_issue = await async_db.get(Issue, first.created_issue_ids[0])
    created_thread = await async_db.get(Thread, first.created_thread_ids[0])
    assert created_issue is not None and created_thread is not None
    assert created_issue.thread_id == created_thread.id
    assert created_issue.issue_number == "1"
    assert created_issue.status == "unread"
    assert created_thread.title == "B.P.R.D.: The Universal Machine"
    assert created_thread.next_unread_issue_id == created_issue.id
    assert [node["ref_id"] for node in plan.nodes_json] == [created_issue.id]
    assert plan.nodes_json[0]["source_cbl_placements"] == [
        {"source_path": source.source_path, "position": 1}
    ]
    assert await async_db.scalar(select(func.count()).select_from(DependencyGroup)) == before_groups
    assert await async_db.scalar(select(func.count()).select_from(Dependency)) == before_dependencies

    second = await commit_existing_cbl_entries_to_reading_plan(
        async_db,
        user_id=user.id,
        plan_id=plan.id,
        list_id=list_id,
        reviewed_source=source,
        reviewed_entries=reviewed_entries,
        reviewed_final_positions=reviewed_order,
        series_decisions={},
        entry_decisions=decisions,
    )
    assert second.created_issue_ids == ()
    assert second.created_thread_ids == ()
    assert second.idempotent_replay is True
    assert second.reused_issue_ids == (created_issue.id,)


@pytest.mark.asyncio
async def test_missing_issue_inserts_before_read_existing_issue_without_rewriting_history(
    async_db: AsyncSession,
) -> None:
    """Series-local insertion preserves the later issue's identity and read facts."""
    user = await get_or_create_user_async(async_db)
    list_id, entry, series_identity = await _seed_missing_source(
        async_db,
        series_external_id="bprd-garden-of-souls",
        issue_external_id="900101",
        issue_number="1",
        series_name="B.P.R.D.: Garden of Souls",
        source_path="Dark Horse/BPRD/Garden of Souls.cbl",
    )
    thread = Thread(
        title="B.P.R.D.: Garden of Souls",
        format="comic",
        issues_remaining=0,
        total_issues=1,
        queue_position=10,
        status="completed",
        reading_progress="completed",
        user_id=user.id,
    )
    async_db.add(thread)
    await async_db.flush()
    read_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    existing = Issue(
        thread_id=thread.id,
        issue_number="2",
        position=1,
        status="read",
        read_at=read_at,
    )
    async_db.add(existing)
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread.id,
            external_identity_id=series_identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    await async_db.flush()
    existing_id = existing.id

    plan = ContinuityPlan(
        user_id=user.id,
        name="B.P.R.D.",
        ordering_mode="strict_sequential",
        lanes_json=[{"id": "main", "name": "Reading order", "order": 0}],
        nodes_json=[
            {
                "id": f"existing-{existing.id}",
                "node_type": "issue",
                "ref_id": existing.id,
                "lane_id": "main",
                "position": 0,
                "label": "Garden of Souls #2",
                "is_checkpoint": False,
                "convergence_gate": [],
            }
        ],
    )
    async_db.add(plan)
    await async_db.flush()
    source, reviewed_entries, reviewed_order, decisions = await _review_missing(
        async_db, user_id=user.id, list_id=list_id, entry_id=entry.id
    )

    result = await commit_existing_cbl_entries_to_reading_plan(
        async_db,
        user_id=user.id,
        plan_id=plan.id,
        list_id=list_id,
        reviewed_source=source,
        reviewed_entries=reviewed_entries,
        reviewed_final_positions=reviewed_order,
        series_decisions={},
        entry_decisions=decisions,
    )
    await async_db.refresh(thread)
    preserved = await async_db.get(Issue, existing_id)
    created = await async_db.get(Issue, result.created_issue_ids[0])

    assert result.created_thread_ids == ()
    assert created is not None and preserved is not None
    assert (created.issue_number, created.position, created.thread_id) == ("1", 1, thread.id)
    assert (preserved.id, preserved.issue_number, preserved.position) == (existing_id, "2", 2)
    assert preserved.status == "read"
    assert preserved.read_at == read_at
    assert thread.status == "active"
    assert thread.total_issues == 2
    assert thread.issues_remaining == 1
    assert thread.next_unread_issue_id == created.id
    assert thread.reading_progress == "in_progress"

    rules = list(
        (
            await async_db.scalars(
                select(ContinuityRule).where(ContinuityRule.note == plan_marker(plan.id))
            )
        ).all()
    )
    assert len(rules) == 1
    assert (rules[0].source_id, rules[0].target_id) == (existing.id, created.id)
