"""Release source projection onto the Reading Plan reader view (#3120)."""

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.models.thread import Thread
from app.schemas.reading_plan_release_source import (
    ReleaseSourceCreate,
    ReleaseSourceUpdate,
)
from app.services import reading_plan_release_source_service as release_service
from app.services import reading_plan_reader as reader_service
from tests.conftest import get_or_create_user_async


async def _make_plan(async_db: AsyncSession, *, user_id: int) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name="Release Reader Plan",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    return plan


async def _make_thread(
    async_db: AsyncSession, *, user_id: int, title: str
) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user_id,
        total_issues=1,
        reading_progress="unstarted",
        created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    return thread


async def _make_identity(
    async_db: AsyncSession, *, external_id: str = "12345"
) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=external_id,
        metadata_json={
            "name": "X-Men",
            "publisher": "Marvel",
            "start_year": 1963,
            "count_of_issues": 12,
        },
    )
    async_db.add(identity)
    await async_db.flush()
    return identity


async def _confirm_mapping(
    async_db: AsyncSession, *, thread_id: int, identity_id: int
) -> None:
    mapping = ThreadExternalSeriesMapping(
        thread_id=thread_id,
        external_identity_id=identity_id,
        status="confirmed",
        evidence_source="test",
    )
    async_db.add(mapping)
    await async_db.flush()


@pytest.mark.asyncio
async def test_reader_includes_release_source_status(async_db: AsyncSession) -> None:
    """The reader view projects release sources with display metadata."""
    user = await get_or_create_user_async(async_db, "release-reader@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Reader X-Men")
    identity = await _make_identity(async_db)
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    created = await release_service.create_source(
        async_db,
        data=ReleaseSourceCreate(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
        ),
        user_id=user.id,
    )

    view = await reader_service.get_reading_plan_reader(
        async_db, user_id=user.id, plan_id=plan.id
    )
    assert len(view.release_sources) == 1
    status = view.release_sources[0]
    assert status.source_id == created.id
    assert status.thread_id == thread.id
    assert status.provider_volume_id == identity.external_id
    assert status.provider_title == "X-Men"
    assert status.provider_publisher == "Marvel"
    assert status.provider_start_year == 1963
    assert status.provider_issue_count == 12
    assert status.enabled is True


@pytest.mark.asyncio
async def test_reader_release_source_status_is_empty_without_subscriptions(
    async_db: AsyncSession,
) -> None:
    """A plan with no release sources projects an empty list, not an error."""
    user = await get_or_create_user_async(async_db, "release-reader-empty@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    await async_db.commit()

    view = await reader_service.get_reading_plan_reader(
        async_db, user_id=user.id, plan_id=plan.id
    )
    assert view.release_sources == []


@pytest.mark.asyncio
async def test_list_release_sources_for_reader_includes_disabled(
    async_db: AsyncSession,
) -> None:
    """The reader surface returns disabled sources so they can be re-enabled."""
    user = await get_or_create_user_async(async_db, "release-reader-disabled@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="Reader Disabled")
    identity = await _make_identity(async_db, external_id="9001")
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    created = await release_service.create_source(
        async_db,
        data=ReleaseSourceCreate(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
        ),
        user_id=user.id,
    )
    await release_service.update_source(
        async_db,
        source_id=created.id,
        data=ReleaseSourceUpdate(enabled=False),
        user_id=user.id,
    )

    statuses = await release_service.list_release_sources_for_reader(
        async_db, plan_id=plan.id, user_id=user.id
    )
    assert len(statuses) == 1
    assert statuses[0].enabled is False
    assert statuses[0].provider_title == "X-Men"


@pytest.mark.asyncio
async def test_reader_release_source_status_rejects_foreign_plan(
    async_db: AsyncSession,
) -> None:
    """Release source status is scoped to the plan owner."""
    user_a = await get_or_create_user_async(async_db, "release-reader-a@test.com")
    user_b = await get_or_create_user_async(async_db, "release-reader-b@test.com")
    plan = await _make_plan(async_db, user_id=user_a.id)
    await async_db.commit()

    with pytest.raises(HTTPException):
        await release_service.list_release_sources_for_reader(
            async_db, plan_id=plan.id, user_id=user_b.id
        )