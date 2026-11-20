"""CBL identity resolution never omits unmatched rows or picks min issue id."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cbl_reference import CBLSource, CBLSourceEntry, CBLSourceList
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.issue import Issue
from app.services.cbl_informational_plan_adoption import (
    InformationalCblAdoptionError,
    adopt_cbl_list_as_informational_plan,
)
from app.services.cbl_source_identity_resolution import (
    report_cbl_source_identity_resolution,
    resolution_is_complete,
)
from app.services.source_backed_reader_order_migration import (
    PRODUCTION_SOURCE_BACKED_SPECS,
    apply_source_backed_reader_order_migration,
)
from app.services.ultimate_universe_production_migration import MigrationInvariantError
from tests.conftest import get_or_create_user_async
from tests.test_series_thread_reattach import _thread_with_numbers


async def _source_list(db: AsyncSession, *, name: str, count: int) -> CBLSourceList:
    source = CBLSource(
        repository=f"test/cbl-identity-{name}-{count}-{datetime.now(UTC).timestamp()}",
        revision_sha="b" * 40,
        synced_at=datetime.now(UTC),
    )
    db.add(source)
    await db.flush()
    source_list = CBLSourceList(
        source_id=source.id,
        source_path="Marvel/identity.cbl",
        name=name,
        declared_issue_count=count,
        content_hash="c" * 64,
        revision_sha="b" * 40,
        active=True,
    )
    db.add(source_list)
    await db.flush()
    return source_list


async def _identity(db: AsyncSession, *, entity_type: str, external_id: str) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type=entity_type,
        external_id=external_id,
        metadata_json={"cover_date": "1998-12-01", "volume_id": "26316"},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _map_issue(
    db: AsyncSession,
    *,
    issue: Issue,
    identity: ExternalIdentity,
) -> None:
    db.add(
        IssueExternalIdentityMapping(
            issue_id=issue.id,
            external_identity_id=identity.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )


@pytest.mark.asyncio
async def test_identity_resolution_keeps_source_order_and_unique_matches(
    async_db: AsyncSession,
) -> None:
    """Unique confirmed mappings are accepted in CBL source order."""
    user = await get_or_create_user_async(async_db)
    _owned_thread, issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Men",
        numbers=["80", "91"],
        queue_position=1,
    )
    source_list = await _source_list(async_db, name="Era Ten", count=2)
    later = await _identity(async_db, entity_type="issue", external_id="91")
    earlier = await _identity(async_db, entity_type="issue", external_id="80")
    await _map_issue(async_db, issue=issues[1], identity=later)
    await _map_issue(async_db, issue=issues[0], identity=earlier)
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=2,
            series_name="X-Men",
            issue_number="91",
            external_issue_identity_id=later.id,
        )
    )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="X-Men",
            issue_number="80",
            external_issue_identity_id=earlier.id,
        )
    )
    await async_db.flush()

    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert [row.position for row in rows] == [1, 2]
    assert [row.chosen_issue_id for row in rows] == [issues[0].id, issues[1].id]
    assert all(row.status == "unique_confirmed_identity" for row in rows)
    assert resolution_is_complete(rows) is True
    plan_count = (
        await async_db.execute(select(func.count()).select_from(ContinuityPlan))
    ).scalar_one()
    assert plan_count == 0


@pytest.mark.asyncio
async def test_identity_resolution_uses_comicvine_volume_and_refuses_min_id(
    async_db: AsyncSession,
) -> None:
    """Volume evidence can pick one copy; same-volume duplicates stay ambiguous."""
    user = await get_or_create_user_async(async_db)
    annual_thread, annual_issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Men",
        numbers=["Annual 1998"],
        queue_position=1,
    )
    own_thread, own_issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Men / Dr. Doom '98 (1998)",
        numbers=["1"],
        queue_position=2,
    )
    copy_a, copy_a_issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Force",
        numbers=["71"],
        queue_position=3,
    )
    copy_b, copy_b_issues = await _thread_with_numbers(
        async_db,
        user_id=user.id,
        title="X-Force (Vol. 1) (1991 - 2002)",
        numbers=["71"],
        queue_position=4,
    )
    annual_id = await _identity(async_db, entity_type="issue", external_id="178128")
    force_id = await _identity(async_db, entity_type="issue", external_id="64544")
    doom_series = await _identity(async_db, entity_type="series", external_id="26316")
    force_series = await _identity(async_db, entity_type="series", external_id="4604")
    await _map_issue(async_db, issue=annual_issues[0], identity=annual_id)
    await _map_issue(async_db, issue=own_issues[0], identity=annual_id)
    await _map_issue(async_db, issue=copy_a_issues[0], identity=force_id)
    await _map_issue(async_db, issue=copy_b_issues[0], identity=force_id)
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=own_thread.id,
            external_identity_id=doom_series.id,
            status="confirmed",
            evidence_source="test",
            confidence=0.95,
        )
    )
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=copy_a.id,
            external_identity_id=force_series.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    async_db.add(
        ThreadExternalSeriesMapping(
            thread_id=copy_b.id,
            external_identity_id=force_series.id,
            status="confirmed",
            evidence_source="test",
            confidence=1.0,
        )
    )
    source_list = await _source_list(async_db, name="Era Ten", count=2)
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="X-Men / Dr. Doom '98",
            issue_number="1",
            external_issue_identity_id=annual_id.id,
            external_series_identity_id=doom_series.id,
        )
    )
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=2,
            series_name="X-Force",
            issue_number="71",
            external_issue_identity_id=force_id.id,
            external_series_identity_id=force_series.id,
        )
    )
    await async_db.flush()

    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert rows[0].status == "resolved_comicvine_volume"
    assert rows[0].chosen_issue_id == own_issues[0].id
    assert rows[0].chosen_issue_id != annual_issues[0].id
    assert rows[1].status == "ambiguous_duplicate_copies"
    assert rows[1].chosen_issue_id is None
    candidate_ids = {candidate.issue_id for candidate in rows[1].candidates}
    assert candidate_ids == {copy_a_issues[0].id, copy_b_issues[0].id}
    assert min(candidate_ids) != own_issues[0].id
    assert resolution_is_complete(rows) is False
    assert annual_thread.title == "X-Men"


@pytest.mark.asyncio
async def test_identity_resolution_reports_unmatched_and_never_adopts(
    async_db: AsyncSession,
) -> None:
    """Unmatched entries stay in source order and adoption is refused."""
    user = await get_or_create_user_async(async_db)
    source_list = await _source_list(async_db, name="Era Ten", count=1)
    missing = await _identity(async_db, entity_type="issue", external_id="44085")
    async_db.add(
        CBLSourceEntry(
            list_id=source_list.id,
            position=1,
            series_name="Marvel Team-Up",
            issue_number="1",
            external_issue_identity_id=missing.id,
        )
    )
    await async_db.flush()

    rows = await report_cbl_source_identity_resolution(
        async_db, user_id=user.id, source_list_id=source_list.id
    )
    assert len(rows) == 1
    assert rows[0].status == "unmatched"
    assert rows[0].chosen_issue_id is None
    assert rows[0].candidates == []
    assert rows[0].comicvine_issue_id == "44085"
    assert resolution_is_complete(rows) is False
    with pytest.raises(InformationalCblAdoptionError, match="must not be adopted"):
        await adopt_cbl_list_as_informational_plan(
            async_db,
            user_id=user.id,
            source_list_id=source_list.id,
            plan_name="Late-90s X-Men Reading Order",
        )
    leftover = (
        await async_db.execute(select(func.count()).select_from(ContinuityPlan))
    ).scalar_one()
    assert leftover == 0


@pytest.mark.asyncio
async def test_xmen_ff_cannot_apply_as_strict_source_backed_plans(
    async_db: AsyncSession,
) -> None:
    """Imported X-Men/FF CBL lists must not compile inferred gates."""
    for key in ("x-men-era-ten", "fantastic-four-early-years"):
        with pytest.raises(MigrationInvariantError, match="held until CBL identity"):
            await apply_source_backed_reader_order_migration(
                async_db,
                snapshot={},
                spec=PRODUCTION_SOURCE_BACKED_SPECS[key],
            )
