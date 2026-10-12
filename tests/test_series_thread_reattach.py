"""Reattach a split series Thread without deleting Issue rows."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.continuity_rule import ContinuityRule
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.models.reading_plan_membership import ReadingPlanIssue
from app.models.thread import Thread
from app.services.cbl_informational_plan_adoption import (
    InformationalCblAdoptionError,
    adopt_cbl_list_as_informational_plan,
)
from app.services.series_thread_reattach import (
    SeriesThreadReattachError,
    reattach_split_series_thread,
)
from app.services.source_backed_reader_order_migration import (
    PRODUCTION_SOURCE_BACKED_SPECS,
    apply_source_backed_reader_order_migration,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError
from tests.conftest import get_or_create_user_async


async def _thread_with_numbers(
    db: AsyncSession,
    *,
    user_id: int,
    title: str,
    numbers: list[str],
    queue_position: int,
    read_through: int = 0,
) -> tuple[Thread, list[Issue]]:
    """Create one owned Thread with stable issue ids."""
    unread = max(len(numbers) - read_through, 0)
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=unread,
        queue_position=queue_position,
        status="active",
        user_id=user_id,
        total_issues=len(numbers),
        created_at=datetime.now(UTC),
    )
    db.add(thread)
    await db.flush()
    issues: list[Issue] = []
    next_unread: int | None = None
    for position, number in enumerate(numbers, start=1):
        status = "read" if position <= read_through else "unread"
        issue = Issue(
            thread_id=thread.id,
            issue_number=number,
            position=position,
            status=status,
            read_at=datetime.now(UTC) if status == "read" else None,
        )
        db.add(issue)
        await db.flush()
        issues.append(issue)
        if status == "unread" and next_unread is None:
            next_unread = issue.id
    thread.next_unread_issue_id = next_unread
    await db.flush()
    return thread, issues


@pytest.mark.asyncio
async def test_reattach_keeps_issue_ids_read_status_and_history(
    async_db: AsyncSession,
) -> None:
    """FF (1970) issues move onto FF (1961) without recreate/delete."""
    user = await get_or_create_user_async(async_db)
    canonical, early = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Fantastic Four (1961)",
        numbers=["1", "16", "102"],
        queue_position=1,
        read_through=1,
    )
    split, later = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Fantastic Four (1970)",
        numbers=["103", "231"],
        queue_position=2,
    )
    series_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="2045",
        metadata_json={},
    )
    async_db.add(series_identity)
    await async_db.flush()
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=canonical.id,
            external_identity_id=series_identity.id,
            status="confirmed",
            evidence_source="derived_from_confirmed_issue_identity",
            confidence=1.0,
        )
    )
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=split.id,
            external_identity_id=series_identity.id,
            status="confirmed",
            evidence_source="broad_cbl_volume_representation",
            confidence=0.95,
        )
    )
    kept_ids = [issue.id for issue in [*early, *later]]
    kept_read_at = early[0].read_at
    await async_db.commit()

    result = await reattach_split_series_thread(
        async_db,
        canonical_thread_id=canonical.id,
        split_thread_id=split.id,
        expected_canonical_title="Fantastic Four (1961)",
        expected_split_title="Fantastic Four (1970)",
    )
    await async_db.commit()

    assert result["moved_issues"] == 2
    assert result["dropped_duplicate_series_mappings"] == 1
    assert result["canonical_total_issues"] == 5
    assert result["canonical_issues_remaining"] == 4
    surviving = await async_db.get(Thread, canonical.id)
    assert surviving is not None
    assert surviving.next_unread_issue_id == early[1].id
    assert await async_db.get(Thread, split.id) is None
    moved = list(
        (
            await async_db.execute(
                select(Issue).where(Issue.id.in_(kept_ids)).order_by(Issue.position)
            )
        ).scalars().all()
    )
    assert [issue.issue_number for issue in moved] == ["1", "16", "102", "103", "231"]
    assert [issue.thread_id for issue in moved] == [canonical.id] * 5
    assert moved[0].status == "read"
    assert moved[0].read_at == kept_read_at
    assert moved[3].status == "unread"
    mappings = list(
        (
            await async_db.execute(
                select(ThreadExternalSeriesMapping).where(
                    ThreadExternalSeriesMapping.thread_id == canonical.id
                )
            )
        ).scalars().all()
    )
    assert len(mappings) == 1
    assert mappings[0].confidence == 1.0


@pytest.mark.asyncio
async def test_reattach_refuses_overlapping_issue_numbers(
    async_db: AsyncSession,
) -> None:
    """Do not merge when numbers collide; Issue rows stay on their Threads."""
    user = await get_or_create_user_async(async_db)
    canonical, _early = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Fantastic Four (1961)",
        numbers=["1", "103"],
        queue_position=1,
    )
    split, later = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="Fantastic Four (1970)",
        numbers=["103"],
        queue_position=2,
    )
    later_id = later[0].id
    await async_db.commit()
    with pytest.raises(SeriesThreadReattachError, match="overlap"):
        await reattach_split_series_thread(
            async_db,
            canonical_thread_id=canonical.id,
            split_thread_id=split.id,
            expected_canonical_title="Fantastic Four (1961)",
            expected_split_title="Fantastic Four (1970)",
        )
    leftover = await async_db.get(Issue, later_id)
    assert leftover is not None
    assert leftover.thread_id == split.id


@pytest.mark.asyncio
async def test_informational_cbl_adoption_adds_membership_without_compiling(
    async_db: AsyncSession,
) -> None:
    """Imported CBL lists become informational plans, not inferred blockers."""
    user = await get_or_create_user_async(async_db)
    thread, issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Men",
        numbers=["80", "91"],
        queue_position=1,
    )
    source = CBLSource(
        repository="test/cbl",
        revision_sha="a" * 40,
        synced_at=datetime.now(UTC),
    )
    async_db.add(source)
    await async_db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Marvel/Teams/X-Men/era-ten.cbl",
        name="[1997-2000] X-Men Era Ten Aftermath (UXRO)",
        declared_issue_count=2,
        content_hash="5" * 64,
        revision_sha="a" * 40,
        active=True,
    )
    async_db.add(source_list)
    await async_db.flush()
    for position, issue in enumerate(issues, start=1):
        identity = ExternalIdentity(
            provider="comicvine",
            entity_type="issue",
            external_id=f"xmen-{issue.issue_number}",
            metadata_json={},
        )
        async_db.add(identity)
        await async_db.flush()
        async_db.add(
            IssueExternalIdentityMapping(
                issue_id=issue.id,
                external_identity_id=identity.id,
                status="confirmed",
                evidence_source="test",
                confidence=1.0,
            )
        )
        async_db.add(
            CBLSourceEntry(
                list_id=source_list.id,
                position=position,
                series_name="X-Men",
                issue_number=issue.issue_number,
                external_issue_identity_id=identity.id,
            )
        )
    await async_db.commit()

    plan = await adopt_cbl_list_as_informational_plan(
        async_db,
        user_id=user.id,
        source_list_id=source_list.id,
        plan_name="Late-90s X-Men Reading Order",
    )
    await async_db.commit()
    assert plan.ordering_mode == "informational"
    membership = list(
        (
            await async_db.execute(
                select(ReadingPlanIssue)
                .where(ReadingPlanIssue.plan_id == plan.id)
                .order_by(ReadingPlanIssue.display_position)
            )
        ).scalars().all()
    )
    assert [row.issue_id for row in membership] == [issues[0].id, issues[1].id]
    compiled = list(
        (
            await async_db.execute(
                select(ContinuityRule).where(ContinuityRule.user_id == user.id)
            )
        ).scalars().all()
    )
    assert compiled == []
    with pytest.raises(InformationalCblAdoptionError, match="already exists"):
        await adopt_cbl_list_as_informational_plan(
            async_db,
            user_id=user.id,
            source_list_id=source_list.id,
            plan_name="Late-90s X-Men Reading Order",
        )
    leftover = await async_db.get(ContinuityPlan, plan.id)
    assert leftover is not None
    assert leftover.ordering_mode == "informational"
    assert thread.id == issues[0].thread_id


@pytest.mark.asyncio
async def test_xmen_ff_cannot_apply_as_strict_source_backed_plans(
    async_db: AsyncSession,
) -> None:
    """Imported X-Men/FF CBL lists must not compile inferred gates."""
    for key in ("x-men-era-ten", "fantastic-four-early-years"):
        with pytest.raises(MigrationInvariantError, match="informational CBL adoption only"):
            await apply_source_backed_reader_order_migration(
                async_db,
                snapshot={},
                spec=PRODUCTION_SOURCE_BACKED_SPECS[key],
            )
