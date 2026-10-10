"""Tests for the Reading Plan release sync service (#3117)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    ThreadExternalSeriesMapping,
)
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.services.reading_plan_release_sync import (
    _parse_store_date,
    sync_release_sources,
)
from tests.conftest import get_or_create_user_async


def _row(pid: str, **kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {"id": pid, "issue_number": pid}
    base.update(kwargs)
    return base


async def _setup(
    async_db: AsyncSession, *, username: str, volume_id: str = "100"
) -> tuple[int, int, int]:
    """Create user, plan, thread, volume identity, confirmed mapping, source."""
    user = await get_or_create_user_async(async_db, username)
    plan = ContinuityPlan(
        user_id=user.id, name="P", ordering_mode="informational", nodes_json=[], lanes_json=[]
    )
    async_db.add(plan)
    await async_db.flush()
    thread = Thread(
        title="T", format="comic", issues_remaining=0, queue_position=1,
        status="active", user_id=user.id, total_issues=0,
        reading_progress="unstarted", created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id=volume_id,
        metadata_json={"name": "Vol"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(ThreadExternalSeriesMapping(
        thread_id=thread.id, external_identity_id=identity.id,
        status="confirmed", evidence_source="test",
    ))
    await async_db.flush()
    source = ReadingPlanReleaseSource(
        plan_id=plan.id, thread_id=thread.id,
        external_identity_id=identity.id, enabled=True,
    )
    async_db.add(source)
    await async_db.flush()
    await async_db.commit()
    return user.id, plan.id, thread.id


def _provider(rows: list[dict[str, object]]) -> AsyncMock:
    mock = AsyncMock()
    mock.fetch_volume_issues.return_value = rows
    return mock


@pytest.mark.asyncio
async def test_parse_store_date() -> None:
    """Store dates parse to UTC; garbage returns None."""
    assert _parse_store_date("2024-01-15") is not None
    assert _parse_store_date("2024-01-15 10:30:00") is not None
    assert _parse_store_date("") is None
    assert _parse_store_date(None) is None
    assert _parse_store_date("not-a-date") is None


@pytest.mark.asyncio
async def test_adopts_released_issues(async_db: AsyncSession) -> None:
    """Issues with store_date <= as_of are adopted."""
    user_id, plan_id, thread_id = await _setup(async_db, username="sync1")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([
        _row("1", store_date="2024-01-15"),
        _row("2", store_date="2024-05-20"),
    ])
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert result.total_adopted == 2
    assert result.total_failures == 0
    assert len(result.sources) == 1
    assert result.sources[0].adopted == 2


@pytest.mark.asyncio
async def test_skips_future_issues(async_db: AsyncSession) -> None:
    """Issues with future store_date are not adopted."""
    user_id, _, _ = await _setup(async_db, username="sync2")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([
        _row("1", store_date="2024-01-15"),
        _row("2", store_date="2024-12-01"),
    ])
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert result.total_adopted == 1
    assert result.sources[0].skipped_future == 1


@pytest.mark.asyncio
async def test_skips_unknown_date(async_db: AsyncSession) -> None:
    """Issues without store_date are skipped, not guessed."""
    user_id, _, _ = await _setup(async_db, username="sync3")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([
        _row("1", store_date="2024-01-15"),
        _row("2"),  # no store_date
        _row("3", store_date=""),
        _row("4", cover_date="2024-02-01"),  # cover_date is not evidence
    ])
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert result.total_adopted == 1
    assert result.sources[0].skipped_unknown_date == 3


@pytest.mark.asyncio
async def test_skips_already_adopted(async_db: AsyncSession) -> None:
    """Already-adopted issues are not duplicated."""
    user_id, plan_id, thread_id = await _setup(async_db, username="sync4")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([_row("1", store_date="2024-01-15")])
    first = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert first.total_adopted == 1
    second = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert second.total_adopted == 0
    assert second.sources[0].skipped_already_adopted == 1


@pytest.mark.asyncio
async def test_volume_fetched_once_for_multiple_plans(async_db: AsyncSession) -> None:
    """One volume fetch serves multiple plans following it."""
    user = await get_or_create_user_async(async_db, "sync5")
    plan_a = ContinuityPlan(user_id=user.id, name="PA", ordering_mode="informational", nodes_json=[], lanes_json=[])
    plan_b = ContinuityPlan(user_id=user.id, name="PB", ordering_mode="informational", nodes_json=[], lanes_json=[])
    async_db.add(plan_a)
    async_db.add(plan_b)
    await async_db.flush()
    thread = Thread(
        title="T", format="comic", issues_remaining=0, queue_position=1,
        status="active", user_id=user.id, total_issues=0,
        reading_progress="unstarted", created_at=datetime.now(UTC),
    )
    async_db.add(thread)
    await async_db.flush()
    identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="200",
        metadata_json={"name": "Vol"},
    )
    async_db.add(identity)
    await async_db.flush()
    async_db.add(ThreadExternalSeriesMapping(
        thread_id=thread.id, external_identity_id=identity.id,
        status="confirmed", evidence_source="test",
    ))
    await async_db.flush()
    for plan in (plan_a, plan_b):
        async_db.add(ReadingPlanReleaseSource(
            plan_id=plan.id, thread_id=thread.id,
            external_identity_id=identity.id, enabled=True,
        ))
    await async_db.flush()
    await async_db.commit()

    provider = _provider([_row("1", store_date="2024-01-15")])
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    result = await sync_release_sources(async_db, user_id=user.id, as_of=as_of, provider=provider)
    assert provider.fetch_volume_issues.call_count == 1
    assert len(result.sources) == 2


@pytest.mark.asyncio
async def test_failure_isolation(async_db: AsyncSession) -> None:
    """One bad volume does not abort other sources."""
    user_id, _, _ = await _setup(async_db, username="sync6", volume_id="300")
    # Second source with a failing volume.
    user = await get_or_create_user_async(async_db, "sync6")
    from sqlalchemy import select as sa_select
    thread = (await async_db.execute(sa_select(Thread).where(Thread.user_id == user.id))).scalars().first()
    assert thread is not None
    plan = (await async_db.execute(sa_select(ContinuityPlan).where(ContinuityPlan.user_id == user.id))).scalars().first()
    assert plan is not None
    bad_identity = ExternalIdentity(
        provider="comicvine", entity_type="series", external_id="999",
        metadata_json={"name": "Bad"},
    )
    async_db.add(bad_identity)
    await async_db.flush()
    async_db.add(ThreadExternalSeriesMapping(
        thread_id=thread.id, external_identity_id=bad_identity.id,
        status="confirmed", evidence_source="test",
    ))
    await async_db.flush()
    async_db.add(ReadingPlanReleaseSource(
        plan_id=plan.id, thread_id=thread.id,
        external_identity_id=bad_identity.id, enabled=True,
    ))
    await async_db.flush()
    await async_db.commit()

    async def fake_fetch(volume_id: int, *, refresh: bool = False) -> list[dict[str, object]]:
        if volume_id == 999:
            raise RuntimeError("provider exploded")
        return [_row("1", store_date="2024-01-15")]

    provider = AsyncMock()
    provider.fetch_volume_issues.side_effect = fake_fetch
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert len(result.volume_fetch_failures) == 1
    assert result.total_adopted == 1  # Good volume still synced.


@pytest.mark.asyncio
async def test_updates_last_synced_at(async_db: AsyncSession) -> None:
    """Successful sync stamps last_synced_at."""
    user_id, plan_id, _ = await _setup(async_db, username="sync7")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([_row("1", store_date="2024-01-15")])
    await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    from sqlalchemy import select as sa_select
    source = (
        await async_db.execute(
            sa_select(ReadingPlanReleaseSource).where(ReadingPlanReleaseSource.plan_id == plan_id)
        )
    ).scalar_one()
    assert source.last_synced_at is not None


@pytest.mark.asyncio
async def test_adopts_issue_on_as_of_boundary(async_db: AsyncSession) -> None:
    """An issue with store_date exactly equal to as_of is adopted."""
    user_id, _, _ = await _setup(async_db, username="sync8")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)
    provider = _provider([_row("1", store_date="2024-06-01")])
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert result.total_adopted == 1
    assert result.sources[0].adopted == 1


@pytest.mark.asyncio
async def test_failed_volume_does_not_stamp_last_synced_at(async_db: AsyncSession) -> None:
    """A source whose volume fetch failed is not marked as successfully synced."""
    user_id, plan_id, _ = await _setup(async_db, username="sync9", volume_id="999")
    as_of = datetime(2024, 6, 1, tzinfo=UTC)

    async def fake_fetch(volume_id: int, *, refresh: bool = False) -> list[dict[str, object]]:
        raise RuntimeError("provider exploded")

    provider = AsyncMock()
    provider.fetch_volume_issues.side_effect = fake_fetch
    result = await sync_release_sources(async_db, user_id=user_id, as_of=as_of, provider=provider)
    assert len(result.volume_fetch_failures) == 1
    assert result.total_adopted == 0
    from sqlalchemy import select as sa_select
    source = (
        await async_db.execute(
            sa_select(ReadingPlanReleaseSource).where(ReadingPlanReleaseSource.plan_id == plan_id)
        )
    ).scalar_one()
    assert source.last_synced_at is None
