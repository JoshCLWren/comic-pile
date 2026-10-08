"""Tests for Reading Plan release sources (#3116)."""

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
from app.services import reading_plan_release_source_service as service
from tests.conftest import get_or_create_user_async


async def _make_plan(async_db: AsyncSession, *, user_id: int) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name="Test Plan",
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    async_db.add(plan)
    await async_db.flush()
    return plan


async def _make_thread(async_db: AsyncSession, *, user_id: int, title: str) -> Thread:
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
        metadata_json={"name": "Test Volume"},
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
async def test_create_and_list_release_source(async_db: AsyncSession) -> None:
    """Create a release source and list it back."""
    user = await get_or_create_user_async(async_db, "release1@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="T1")
    identity = await _make_identity(async_db)
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    created = await service.create_source(
        async_db,
        data=ReleaseSourceCreate(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
        ),
        user_id=user.id,
    )
    assert created.plan_id == plan.id
    assert created.thread_id == thread.id
    assert created.provider == "comicvine"
    assert created.provider_title == "Test Volume"
    assert created.enabled is True

    listed = await service.list_sources(async_db, plan_id=plan.id, user_id=user.id)
    assert len(listed) == 1
    assert listed[0].id == created.id


@pytest.mark.asyncio
async def test_create_is_retry_safe(async_db: AsyncSession) -> None:
    """Duplicate creates return the existing row."""
    user = await get_or_create_user_async(async_db, "release2@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="T2")
    identity = await _make_identity(async_db, external_id="999")
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    data = ReleaseSourceCreate(
        plan_id=plan.id, thread_id=thread.id, external_identity_id=identity.id
    )
    first = await service.create_source(async_db, data=data, user_id=user.id)
    second = await service.create_source(async_db, data=data, user_id=user.id)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_rejects_unconfirmed_mapping(async_db: AsyncSession) -> None:
    """Unconfirmed provider mappings cannot become release sources."""
    user = await get_or_create_user_async(async_db, "release3@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="T3")
    identity = await _make_identity(async_db, external_id="888")
    # No confirmed mapping created.
    await async_db.commit()

    with pytest.raises(HTTPException, match="confirmed mapping"):
        await service.create_source(
            async_db,
            data=ReleaseSourceCreate(
                plan_id=plan.id,
                thread_id=thread.id,
                external_identity_id=identity.id,
            ),
            user_id=user.id,
        )


@pytest.mark.asyncio
async def test_rejects_cross_user_plan_thread(async_db: AsyncSession) -> None:
    """Plan and thread must be owned by the same user."""
    user_a = await get_or_create_user_async(async_db, "release4a@test.com")
    user_b = await get_or_create_user_async(async_db, "release4b@test.com")
    plan = await _make_plan(async_db, user_id=user_a.id)
    thread = await _make_thread(async_db, user_id=user_b.id, title="T4")
    identity = await _make_identity(async_db, external_id="777")
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    # Plan owned by A, thread owned by B: plan lookup scoped to B fails first.
    with pytest.raises(HTTPException):
        await service.create_source(
            async_db,
            data=ReleaseSourceCreate(
                plan_id=plan.id,
                thread_id=thread.id,
                external_identity_id=identity.id,
            ),
            user_id=user_b.id,
        )


@pytest.mark.asyncio
async def test_disable_is_idempotent(async_db: AsyncSession) -> None:
    """Disable/re-enable is idempotent and non-destructive."""
    user = await get_or_create_user_async(async_db, "release5@test.com")
    plan = await _make_plan(async_db, user_id=user.id)
    thread = await _make_thread(async_db, user_id=user.id, title="T5")
    identity = await _make_identity(async_db, external_id="666")
    await _confirm_mapping(async_db, thread_id=thread.id, identity_id=identity.id)
    await async_db.commit()

    created = await service.create_source(
        async_db,
        data=ReleaseSourceCreate(
            plan_id=plan.id,
            thread_id=thread.id,
            external_identity_id=identity.id,
        ),
        user_id=user.id,
    )
    disabled = await service.update_source(
        async_db,
        source_id=created.id,
        data=ReleaseSourceUpdate(enabled=False),
        user_id=user.id,
    )
    assert disabled.enabled is False
    # Idempotent: disabling again is fine.
    again = await service.update_source(
        async_db,
        source_id=created.id,
        data=ReleaseSourceUpdate(enabled=False),
        user_id=user.id,
    )
    assert again.enabled is False
    # Re-enable.
    enabled = await service.update_source(
        async_db,
        source_id=created.id,
        data=ReleaseSourceUpdate(enabled=True),
        user_id=user.id,
    )
    assert enabled.enabled is True
