"""PostgreSQL coverage for the generic Step 27 reader-order migration."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.dependency import Dependency
from app.models.dependency_group import DependencyGroup, DependencyGroupMembership
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.source_backed_reader_order_migration import (
    SourceBackedReaderOrderSpec,
    apply_source_backed_reader_order_migration,
    build_source_backed_reader_order_dry_run,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError
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
async def test_source_backed_migration_accepts_group_superset_and_replaces_live_order(
    async_db: AsyncSession,
) -> None:
    """Ignore extra group members while replacing live legacy order authority."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="A",
            queue_position=1,
            status="read",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="B",
            queue_position=2,
            status="unread",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="C",
            queue_position=3,
            status="read",
        ),
        await _thread_issue(
            async_db,
            user_id=user.id,
            title="D",
            queue_position=4,
            status="unread",
        ),
    ]
    extra_thread, extra_issue = await _thread_issue(
        async_db,
        user_id=user.id,
        title="Future extra member",
        queue_position=5,
        status="unread",
    )
    issues = [row[1] for row in rows]

    source = CBLSource(
        repository="test/step27-generic",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Test/Absolute.cbl",
        name="Absolute Test",
        declared_issue_count=4,
        content_hash="a" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()

    for position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"generic-step27-{position}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="step27-test",
                confidence=1.0,
            )
        )
        async_db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=position,
                series_name=f"Test {position}",
                issue_number="1",
                external_issue_identity_id=identity.id,
            )
        )

    group = DependencyGroup(
        user_id=user.id,
        name="Absolute Test",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    memberships = []
    for issue in [*issues, extra_issue]:
        membership = DependencyGroupMembership(group_id=group.id, issue_id=issue.id)
        memberships.append(membership)
        async_db.add(membership)
    await async_db.flush()
    extra_membership_id = memberships[-1].id

    source_dependency = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[3].id,
        note=f"cbl-order:source:{source_list.content_hash}:1->4",
        created_at=datetime.now(UTC),
    )
    explicit_dependency = Dependency(
        source_issue_id=issues[1].id,
        target_issue_id=issues[3].id,
        note="classified reader order",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([source_dependency, explicit_dependency])
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    spec = SourceBackedReaderOrderSpec(
        user_id=user.id,
        source_list_id=source_list.id,
        dependency_group_id=group.id,
        expected_content_hash=source_list.content_hash,
        expected_positions=4,
        plan_name="Absolute Test Plan",
        expected_source_path=source_list.source_path,
        reader_order_dependency_ids=(explicit_dependency.id,),
    )
    snapshot = await build_source_backed_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is True, snapshot["errors"]
    repeated_snapshot = await build_source_backed_reader_order_dry_run(async_db, spec)
    assert repeated_snapshot["snapshot_token"] == snapshot["snapshot_token"]
    assert snapshot["dependency_group"]["membership_count"] == 5
    assert snapshot["dependency_group"]["extra_issue_ids"] == [extra_issue.id]
    assert snapshot["explicit_reader_order_dependencies"][0]["live"] is True
    assert snapshot["explicit_reader_order_dependencies"][0]["implied_by_plan"] is True
    assert snapshot["historical_gap_bridges"] == [
        {
            "source_position": 2,
            "source_issue_id": issues[1].id,
            "target_position": 4,
            "target_issue_id": issues[3].id,
        }
    ]

    before_memberships = await async_db.scalar(
        select(func.count())
        .select_from(DependencyGroupMembership)
        .where(DependencyGroupMembership.group_id == group.id)
    )
    source_list.revision_sha = "c" * 40
    await async_db.flush()
    with pytest.raises(MigrationInvariantError, match="live state changed"):
        await apply_source_backed_reader_order_migration(
            async_db,
            snapshot=snapshot,
            spec=spec,
        )
    await async_db.rollback()
    for persisted in (
        source_list,
        group,
        source_dependency,
        explicit_dependency,
        extra_issue,
        *issues,
    ):
        await async_db.refresh(persisted)

    receipt = await apply_source_backed_reader_order_migration(
        async_db,
        snapshot=snapshot,
        spec=spec,
    )
    await async_db.commit()

    assert receipt["removed_source_dependency_count"] == 1
    assert receipt["removed_explicit_reader_order_dependency_count"] == 1
    assert await async_db.get(Dependency, source_dependency.id) is None
    assert await async_db.get(Dependency, explicit_dependency.id) is None
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(DependencyGroupMembership)
            .where(DependencyGroupMembership.group_id == group.id)
        )
        == before_memberships
    )
    assert (
        await async_db.get(DependencyGroupMembership, extra_membership_id) is not None
    )

    plan = await async_db.get(ContinuityPlan, receipt["plan_id"])
    assert plan is not None
    assert plan.ordering_mode == "strict_sequential"
    assert [node["ref_id"] for node in plan.nodes_json] == [
        issue.id for issue in issues
    ]
    assert plan.nodes_json[-1]["convergence_gate"] == [
        {"node_type": "issue", "node_id": f"issue-{issues[1].id}"}
    ]
    assert extra_thread.id not in receipt["affected_roll_eligible_thread_ids"]


@pytest.mark.asyncio
async def test_source_backed_migration_refuses_needs_review_intersection(
    async_db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-backed dry-run fails closed when needs_review edges touch the plan."""
    user = await get_or_create_user_async(async_db)
    rows = [
        await _thread_issue(
            async_db,
            user_id=user.id,
            title=title,
            queue_position=position,
            status=status,
        )
        for position, (title, status) in enumerate(
            (("A", "read"), ("B", "unread"), ("C", "read"), ("D", "unread")),
            start=1,
        )
    ]
    issues = [row[1] for row in rows]

    source = CBLSource(
        repository="test/step27-needs-review",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="DC/Test/NeedsReview.cbl",
        name="Needs Review Source",
        declared_issue_count=4,
        content_hash="n" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    for position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"needs-review-{position}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="step27-test",
                confidence=1.0,
            )
        )
        async_db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=position,
                series_name=f"Test {position}",
                issue_number="1",
                external_issue_identity_id=identity.id,
            )
        )

    group = DependencyGroup(
        user_id=user.id,
        name="Needs Review Source",
        created_at=datetime.now(UTC),
    )
    async_db.add(group)
    await async_db.flush()
    for issue in issues:
        async_db.add(DependencyGroupMembership(group_id=group.id, issue_id=issue.id))

    source_dependency = Dependency(
        source_issue_id=issues[0].id,
        target_issue_id=issues[3].id,
        note=f"cbl-order:source:{source_list.content_hash}:1->4",
        created_at=datetime.now(UTC),
    )
    needs_review = Dependency(
        source_issue_id=issues[1].id,
        target_issue_id=issues[3].id,
        note="needs human review",
        created_at=datetime.now(UTC),
    )
    async_db.add_all([source_dependency, needs_review])
    await async_db.flush()
    await refresh_user_blocked_status(user.id, async_db)
    await async_db.commit()

    monkeypatch.setattr(
        "app.services.source_backed_reader_order_migration._load_step14_index",
        lambda: {},
    )
    monkeypatch.setattr(
        "app.services.source_backed_reader_order_migration._explicit_classifications",
        lambda _index: ({needs_review.id: "needs_review"}, {}),
    )

    spec = SourceBackedReaderOrderSpec(
        user_id=user.id,
        source_list_id=source_list.id,
        dependency_group_id=group.id,
        expected_content_hash=source_list.content_hash,
        expected_positions=4,
        plan_name="Needs Review Source Plan",
        expected_source_path=source_list.source_path,
        reader_order_dependency_ids=(),
    )
    snapshot = await build_source_backed_reader_order_dry_run(async_db, spec)
    assert snapshot["ok"] is False
    assert any("needs_review dependencies touch this plan" in error for error in snapshot["errors"])
    assert [row["id"] for row in snapshot["needs_review_dependencies"]] == [needs_review.id]
