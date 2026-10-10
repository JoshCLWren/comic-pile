"""Contract tests for Reading Plan release-source sync (#3117).

These exercise the real service against the real database with a fake provider
client, so they prove the release gate, dedupe, failure isolation, and
``last_synced_at`` semantics rather than mock choreography.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Issue, Thread, User
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)
from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.services.reading_plan_sync_service import parse_store_date, sync_released_issues
from comic_pile.comicvine_provider import ComicVineClient, ComicVineError, ComicVineResponse
from tests.conftest import get_or_create_user_async

FIXED_AS_OF = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
FIXED_SYNCED_AT = datetime(2025, 6, 15, 12, 30, tzinfo=UTC)


@dataclass
class _FakeProvider(ComicVineClient):
    """Provider double that records fetch calls and replays scripted rosters."""

    rosters: dict[int, list[dict[str, object]]] = field(default_factory=dict)
    failures: dict[int, Exception] = field(default_factory=dict)
    calls: list[tuple[int, bool]] = field(default_factory=list)

    def __init__(
        self,
        rosters: dict[int, list[dict[str, object]]] | None = None,
        failures: dict[int, Exception] | None = None,
    ) -> None:
        self.rosters = rosters or {}
        self.failures = failures or {}
        self.calls = []

    async def fetch_volume_issues(
        self, volume_id: int, *, refresh: bool = False
    ) -> list[dict[str, object]]:
        self.calls.append((volume_id, refresh))
        if volume_id in self.failures:
            raise self.failures[volume_id]
        return list(self.rosters.get(volume_id, []))

    async def fetch_issue(self, issue_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("fake provider does not hydrate issues")

    async def fetch_story_arc(self, arc_id: int, *, refresh: bool = False) -> ComicVineResponse:
        raise ComicVineError("fake provider has no story arcs")


def _roster_row(
    issue_id: int,
    issue_number: str,
    store_date: str | None,
) -> dict[str, object]:
    return {
        "id": issue_id,
        "issue_number": issue_number,
        "name": f"Fixture Saga #{issue_number}",
        "store_date": store_date,
        "cover_date": "1999-01-01",
        "site_detail_url": f"https://comicvine.gamespot.com/issue/4000-{issue_id}/",
    }


async def _make_plan(db: AsyncSession, *, user_id: int, name: str) -> ContinuityPlan:
    plan = ContinuityPlan(
        user_id=user_id,
        name=name,
        ordering_mode="informational",
        nodes_json=[],
        lanes_json=[],
    )
    db.add(plan)
    await db.flush()
    return plan


async def _make_thread(db: AsyncSession, *, user_id: int, title: str) -> Thread:
    thread = Thread(
        title=title,
        format="comic",
        issues_remaining=0,
        queue_position=1,
        status="active",
        user_id=user_id,
    )
    db.add(thread)
    await db.flush()
    return thread


async def _make_volume(db: AsyncSession, *, volume_id: int) -> ExternalIdentity:
    identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id=str(volume_id),
        metadata_json={"name": f"Fixture Saga {volume_id}"},
    )
    db.add(identity)
    await db.flush()
    return identity


async def _confirm_mapping(
    db: AsyncSession, *, thread_id: int, identity_id: int
) -> None:
    db.add(
        ThreadExternalSeriesMapping(
            thread_id=thread_id,
            external_identity_id=identity_id,
            status="confirmed",
            evidence_source="test",
        )
    )
    await db.flush()


async def _subscribe(
    db: AsyncSession,
    *,
    plan: ContinuityPlan,
    thread: Thread,
    identity: ExternalIdentity,
    enabled: bool = True,
) -> ReadingPlanReleaseSource:
    source = ReadingPlanReleaseSource(
        plan_id=plan.id,
        thread_id=thread.id,
        external_identity_id=identity.id,
        enabled=enabled,
    )
    db.add(source)
    await db.flush()
    return source


async def _issue_numbers(db: AsyncSession, *, thread_id: int) -> list[str]:
    rows = await db.execute(
        select(Issue.issue_number)
        .where(Issue.thread_id == thread_id)
        .order_by(Issue.position, Issue.id)
    )
    return list(rows.scalars().all())


async def _sync(
    db: AsyncSession,
    *,
    user_id: int,
    provider: _FakeProvider,
    as_of: datetime = FIXED_AS_OF,
    refresh: bool = True,
):
    return await sync_released_issues(
        db,
        user_id=user_id,
        as_of=as_of,
        refresh=refresh,
        client=provider,
        now=lambda: FIXED_SYNCED_AT,
    )


async def _single_source_fixture(
    db: AsyncSession,
    *,
    username: str,
    volume_id: int = 2001,
) -> tuple[User, Thread, ReadingPlanReleaseSource]:
    user = await get_or_create_user_async(db, username)
    plan = await _make_plan(db, user_id=user.id, name=f"Plan {volume_id}")
    thread = await _make_thread(db, user_id=user.id, title=f"Thread {volume_id}")
    identity = await _make_volume(db, volume_id=volume_id)
    await _confirm_mapping(db, thread_id=thread.id, identity_id=identity.id)
    source = await _subscribe(
        db, plan=plan, thread=thread, identity=identity
    )
    return user, thread, source


# --------------------------------------------------------------------------
# store_date normalization
# --------------------------------------------------------------------------


def test_parse_store_date_normalizes_provider_shapes() -> None:
    """Provider date shapes all normalize to aware UTC; junk returns None."""
    assert parse_store_date("2025-06-01") == datetime(2025, 6, 1, tzinfo=UTC)
    assert parse_store_date("2025-06-01T00:00:00Z") == datetime(2025, 6, 1, tzinfo=UTC)
    assert parse_store_date("2025-06-01T02:00:00+02:00") == datetime(
        2025, 6, 1, tzinfo=UTC
    )
    assert parse_store_date(None) is None
    assert parse_store_date("   ") is None
    assert parse_store_date("not-a-date") is None


# --------------------------------------------------------------------------
# Release gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_adopts_only_released_issues(async_db: AsyncSession) -> None:
    """Future solicitations and unknown-date issues are never adopted."""
    user, thread, source = await _single_source_fixture(
        async_db, username="sync_gate@test.com"
    )
    provider = _FakeProvider(
        rosters={
            2001: [
                _roster_row(101, "1", "2025-06-01"),
                _roster_row(102, "2", "2025-12-01"),
                _roster_row(103, "3", None),
                _roster_row(104, "4", "garbage"),
            ]
        }
    )

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.created_issues == 1
    assert report.future_skips == 1
    assert report.unknown_date_skips == 2
    assert report.failed_sources == 0
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1"]
    assert provider.calls == [(2001, True)]

    await async_db.refresh(source)
    assert source.last_synced_at == FIXED_SYNCED_AT


@pytest.mark.asyncio
async def test_store_date_on_boundary_is_adopted(async_db: AsyncSession) -> None:
    """A store_date exactly equal to as_of counts as released."""
    user, thread, _ = await _single_source_fixture(
        async_db, username="sync_boundary@test.com"
    )
    provider = _FakeProvider(
        rosters={2001: [_roster_row(201, "1", "2025-06-15T12:00:00Z")]}
    )

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.created_issues == 1
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1"]


@pytest.mark.asyncio
async def test_naive_as_of_is_treated_as_utc(async_db: AsyncSession) -> None:
    """A naive boundary is interpreted as UTC rather than local time."""
    user, thread, _ = await _single_source_fixture(
        async_db, username="sync_naive@test.com"
    )
    provider = _FakeProvider(
        rosters={2001: [_roster_row(301, "1", "2025-06-15T12:00:00Z")]}
    )

    report = await _sync(
        async_db,
        user_id=user.id,
        provider=provider,
        as_of=datetime(2025, 6, 15, 12, 0),
    )

    assert report.created_issues == 1
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1"]


@pytest.mark.asyncio
async def test_issue_number_alone_never_implies_release(
    async_db: AsyncSession,
) -> None:
    """A high issue number with no store_date stays unadopted."""
    user, thread, _ = await _single_source_fixture(
        async_db, username="sync_number_only@test.com"
    )
    provider = _FakeProvider(
        rosters={2001: [_roster_row(401, "900", None)]}
    )

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.created_issues == 0
    assert report.unknown_date_skips == 1
    assert await _issue_numbers(async_db, thread_id=thread.id) == []


# --------------------------------------------------------------------------
# Idempotency and duplicate subscriptions
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repeat_sync_reuses_existing_issue(async_db: AsyncSession) -> None:
    """Re-running the same sync never creates a second Issue row."""
    user, thread, _ = await _single_source_fixture(
        async_db, username="sync_retry@test.com"
    )
    provider = _FakeProvider(
        rosters={2001: [_roster_row(501, "1", "2025-06-01")]}
    )

    first = await _sync(async_db, user_id=user.id, provider=provider)
    second = await _sync(async_db, user_id=user.id, provider=provider)

    assert first.created_issues == 1
    assert second.created_issues == 0
    assert second.reused_issues == 1
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1"]

    issue_count = await async_db.scalar(
        select(func.count())
        .select_from(Issue)
        .join(IssueExternalIdentityMapping, IssueExternalIdentityMapping.issue_id == Issue.id)
        .join(
            ExternalIdentity,
            ExternalIdentity.id == IssueExternalIdentityMapping.external_identity_id,
        )
        .where(ExternalIdentity.external_id == "501")
    )
    assert issue_count == 1


@pytest.mark.asyncio
async def test_shared_volume_fetches_once_for_two_plans(
    async_db: AsyncSession,
) -> None:
    """Two plans on one volume fetch one roster and converge on one Issue."""
    user = await get_or_create_user_async(async_db, "sync_shared_volume@test.com")
    plan_a = await _make_plan(db := async_db, user_id=user.id, name="Plan A")
    plan_b = await _make_plan(db, user_id=user.id, name="Plan B")
    thread = await _make_thread(db, user_id=user.id, title="Shared thread")
    identity = await _make_volume(db, volume_id=3001)
    await _confirm_mapping(db, thread_id=thread.id, identity_id=identity.id)
    await _subscribe(db, plan=plan_a, thread=thread, identity=identity)
    await _subscribe(db, plan=plan_b, thread=thread, identity=identity)
    await db.commit()

    provider = _FakeProvider(
        rosters={3001: [_roster_row(601, "1", "2025-06-01")]}
    )
    report = await _sync(db, user_id=user.id, provider=provider)

    assert provider.calls == [(3001, True)]
    assert report.successful_sources == 2
    assert report.created_issues == 1
    assert report.reused_issues == 1
    assert await _issue_numbers(db, thread_id=thread.id) == ["1"]


@pytest.mark.asyncio
async def test_disabled_sources_are_ignored(async_db: AsyncSession) -> None:
    """Disabled sources are counted but never fetched or adopted."""
    user = await get_or_create_user_async(async_db, "sync_disabled@test.com")
    plan = await _make_plan(db := async_db, user_id=user.id, name="Plan")
    thread = await _make_thread(db, user_id=user.id, title="Disabled thread")
    identity = await _make_volume(db, volume_id=4001)
    await _confirm_mapping(db, thread_id=thread.id, identity_id=identity.id)
    source = await _subscribe(
        db, plan=plan, thread=thread, identity=identity, enabled=False
    )
    await db.commit()

    provider = _FakeProvider(
        rosters={4001: [_roster_row(701, "1", "2025-06-01")]}
    )
    report = await _sync(db, user_id=user.id, provider=provider)

    assert report.total_sources == 1
    assert report.enabled_sources == 0
    assert report.checked_sources == 0
    assert provider.calls == []
    assert await _issue_numbers(db, thread_id=thread.id) == []

    await db.refresh(source)
    assert source.last_synced_at is None


@pytest.mark.asyncio
async def test_user_without_sources_is_a_no_op(async_db: AsyncSession) -> None:
    """A user with no sources reports a clean empty run."""
    user = await get_or_create_user_async(async_db, "sync_empty@test.com")
    provider = _FakeProvider()

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.total_sources == 0
    assert report.enabled_sources == 0
    assert report.failed_sources == 0
    assert provider.calls == []


# --------------------------------------------------------------------------
# Ownership isolation
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_never_crosses_user_boundaries(async_db: AsyncSession) -> None:
    """One reader's sync cannot adopt into another reader's thread."""
    owner = await get_or_create_user_async(async_db, "sync_owner@test.com")
    other = await get_or_create_user_async(async_db, "sync_other@test.com")
    plan = await _make_plan(db := async_db, user_id=owner.id, name="Owner plan")
    thread = await _make_thread(db, user_id=owner.id, title="Owner thread")
    identity = await _make_volume(db, volume_id=5001)
    await _confirm_mapping(db, thread_id=thread.id, identity_id=identity.id)
    await _subscribe(db, plan=plan, thread=thread, identity=identity)
    await db.commit()

    provider = _FakeProvider(
        rosters={5001: [_roster_row(801, "1", "2025-06-01")]}
    )
    report = await _sync(db, user_id=other.id, provider=provider)

    assert report.enabled_sources == 0
    assert provider.calls == []
    assert await _issue_numbers(db, thread_id=thread.id) == []


# --------------------------------------------------------------------------
# Failure isolation and last_synced_at semantics
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_volume_failure_isolated_and_not_marked_current(
    async_db: AsyncSession,
) -> None:
    """A failing volume reports a failure and leaves last_synced_at unset."""
    user, thread, source = await _single_source_fixture(
        async_db, username="sync_volume_fail@test.com", volume_id=6001
    )
    provider = _FakeProvider(
        failures={6001: ComicVineError("ComicVine API error")}
    )

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.failed_sources == 1
    assert report.successful_sources == 0
    assert len(report.failures) == 1
    failure = report.failures[0]
    assert failure.source_id == source.id
    assert failure.volume_id == 6001
    assert "ComicVine API error" in failure.error
    assert report.success is False

    await async_db.refresh(source)
    assert source.last_synced_at is None


@pytest.mark.asyncio
async def test_one_failing_volume_does_not_block_another(
    async_db: AsyncSession,
) -> None:
    """A provider failure for one volume leaves the other volume current."""
    user, ok_thread, ok_source = await _single_source_fixture(
        async_db, username="sync_partial@test.com", volume_id=7001
    )
    failing_plan = await _make_plan(db := async_db, user_id=user.id, name="Fail plan")
    failing_thread = await _make_thread(db, user_id=user.id, title="Fail thread")
    failing_identity = await _make_volume(db, volume_id=7002)
    await _confirm_mapping(
        db, thread_id=failing_thread.id, identity_id=failing_identity.id
    )
    await _subscribe(db, plan=failing_plan, thread=failing_thread, identity=failing_identity)
    await db.commit()

    provider = _FakeProvider(
        rosters={7001: [_roster_row(901, "1", "2025-06-01")]},
        failures={7002: ComicVineError("rate limited")},
    )
    report = await _sync(db, user_id=user.id, provider=provider)

    assert report.successful_sources == 1
    assert report.failed_sources == 1
    assert report.created_issues == 1
    assert await _issue_numbers(db, thread_id=ok_thread.id) == ["1"]

    await db.refresh(ok_source)
    assert ok_source.last_synced_at == FIXED_SYNCED_AT


@pytest.mark.asyncio
async def test_demoted_mapping_fails_source_without_stamping(
    async_db: AsyncSession,
) -> None:
    """A demoted volume mapping fails the source instead of adopting."""
    user, thread, source = await _single_source_fixture(
        async_db, username="sync_demoted@test.com", volume_id=8001
    )

    await async_db.execute(
        sa_update(ThreadExternalSeriesMapping)
        .where(
            ThreadExternalSeriesMapping.thread_id == thread.id,
            ThreadExternalSeriesMapping.external_identity_id == source.external_identity_id,
        )
        .values(status="candidate")
    )
    await async_db.commit()

    provider = _FakeProvider(
        rosters={8001: [_roster_row(1001, "1", "2025-06-01")]}
    )
    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.failed_sources == 1
    assert "no longer a confirmed" in report.failures[0].error
    assert await _issue_numbers(async_db, thread_id=thread.id) == []

    await async_db.refresh(source)
    assert source.last_synced_at is None


@pytest.mark.asyncio
async def test_missing_provider_client_key_fails_cleanly(
    async_db: AsyncSession,
) -> None:
    """A missing ComicVine API key reports every source as failed, not crashed."""

    def _explode() -> ComicVineClient:
        raise ValueError("api_key is required")

    user, thread, source = await _single_source_fixture(
        async_db, username="sync_no_key@test.com", volume_id=9001
    )

    report = await sync_released_issues(
        async_db,
        user_id=user.id,
        as_of=FIXED_AS_OF,
        refresh=True,
        client_factory=_explode,
    )

    assert report.failed_sources == 1
    assert "api_key is required" in report.failures[0].error
    assert await _issue_numbers(async_db, thread_id=thread.id) == []

    await async_db.refresh(source)
    assert source.last_synced_at is None


@pytest.mark.asyncio
async def test_corrupt_volume_id_isolated_and_does_not_abort_others(
    async_db: AsyncSession,
) -> None:
    """A source with a non-numeric volume id fails without aborting peers."""
    user, ok_thread, ok_source = await _single_source_fixture(
        async_db, username="sync_corrupt@test.com", volume_id=14001
    )
    bad_plan = await _make_plan(db := async_db, user_id=user.id, name="Bad plan")
    bad_thread = await _make_thread(db, user_id=user.id, title="Bad thread")
    bad_identity = await _make_volume(db, volume_id=14002)
    await _confirm_mapping(db, thread_id=bad_thread.id, identity_id=bad_identity.id)
    bad_source = await _subscribe(db, plan=bad_plan, thread=bad_thread, identity=bad_identity)
    await async_db.execute(
        sa_update(ExternalIdentity)
        .where(ExternalIdentity.id == bad_identity.id)
        .values(external_id="not-a-volume")
    )
    await async_db.commit()

    provider = _FakeProvider(
        rosters={14001: [_roster_row(1401, "1", "2025-06-01")]}
    )
    report = await _sync(db, user_id=user.id, provider=provider)

    assert report.failed_sources == 1
    assert report.successful_sources == 1
    assert "non-numeric" in report.failures[0].error
    assert await _issue_numbers(db, thread_id=ok_thread.id) == ["1"]
    assert await _issue_numbers(db, thread_id=bad_thread.id) == []

    await db.refresh(ok_source)
    assert ok_source.last_synced_at == FIXED_SYNCED_AT
    await db.refresh(bad_source)
    assert bad_source.last_synced_at is None


@pytest.mark.asyncio
async def test_single_bad_issue_does_not_fail_the_source(
    async_db: AsyncSession,
) -> None:
    """A malformed issue row is isolated while its siblings still adopt."""
    user, thread, _ = await _single_source_fixture(
        async_db, username="sync_bad_issue@test.com", volume_id=11001
    )
    provider = _FakeProvider(
        rosters={
            11001: [
                _roster_row(1101, "1", "2025-06-01"),
                {"id": None, "issue_number": "2", "store_date": "2025-06-01"},
                _roster_row(1102, "3", "2025-06-01"),
            ]
        }
    )

    report = await _sync(async_db, user_id=user.id, provider=provider)

    assert report.successful_sources == 1
    assert report.created_issues == 2
    assert report.issue_failures == 1
    assert report.failed_sources == 0
    assert await _issue_numbers(async_db, thread_id=thread.id) == ["1", "3"]


@pytest.mark.asyncio
async def test_sync_writes_survive_a_real_commit(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
) -> None:
    """Adopted issues and last_synced_at persist beyond the sync session.

    The endpoint commits the run, so this proves a fresh connection observes
    both the canonical Issue and the advanced sync timestamp.
    """
    db = async_db_committed
    user, thread, source = await _single_source_fixture(
        db, username="sync_committed@test.com", volume_id=13001
    )
    provider = _FakeProvider(
        rosters={13001: [_roster_row(1301, "1", "2025-06-01")]}
    )

    report = await _sync(db, user_id=user.id, provider=provider)
    await db.commit()

    assert report.created_issues == 1

    verifier = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with verifier() as fresh:
        issue_number = await fresh.scalar(
            select(Issue.issue_number).where(Issue.thread_id == thread.id)
        )
        persisted = await fresh.scalar(
            select(ReadingPlanReleaseSource.last_synced_at).where(
                ReadingPlanReleaseSource.id == source.id
            )
        )
    assert issue_number == "1"
    assert persisted is not None
    assert persisted.tzinfo is not None


@pytest.mark.asyncio
async def test_refresh_flag_reaches_the_provider(async_db: AsyncSession) -> None:
    """The refresh flag is forwarded to the provider roster fetch."""
    user, _, _ = await _single_source_fixture(
        async_db, username="sync_refresh@test.com", volume_id=12001
    )
    provider = _FakeProvider()

    await _sync(async_db, user_id=user.id, provider=provider, refresh=False)

    assert provider.calls == [(12001, False)]