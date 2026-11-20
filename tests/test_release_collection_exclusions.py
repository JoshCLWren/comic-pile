"""Release sync honors durable collection intent at adoption and extension boundaries."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.models import Issue
from app.models.collection_exclusion import CollectionExclusion
from app.models.continuity_plan import ContinuityPlan
from app.models.external_identity import ExternalIdentity
from app.models.reading_plan_membership import ReadingPlanIssue
from app.services.reading_plan_release_extension import extend_plans_with_issue
from app.services.reading_plan_sync_service import sync_released_issues
from tests.conftest import get_or_create_user_async
from tests.test_reading_plan_sync_service import (
    FIXED_AS_OF,
    _FakeProvider,
    _confirm_mapping,
    _make_thread,
    _roster_row,
    _single_source_fixture,
    _subscribe,
)


async def test_excluded_volume_survives_thread_deletion_and_followed_reimport(
    async_db: AsyncSession,
):
    """A removed Thread does not remove an external-volume exclusion or revive its feed."""
    user, thread, source = await _single_source_fixture(
        async_db, username="exclude_volume", volume_id=10001
    )
    plan = await async_db.get(ContinuityPlan, source.plan_id)
    identity = await async_db.get(ExternalIdentity, source.external_identity_id)
    assert plan is not None and identity is not None
    async_db.add(
        CollectionExclusion(user_id=user.id, provider="comicvine", external_volume_id="4050-10001")
    )
    await async_db.flush()
    await async_db.delete(thread)
    await async_db.flush()
    replacement = await _make_thread(async_db, user_id=user.id, title="Alternate source spelling")
    await _confirm_mapping(async_db, thread_id=replacement.id, identity_id=identity.id)
    new_source = await _subscribe(async_db, plan=plan, thread=replacement, identity=identity)
    await async_db.commit()
    provider = _FakeProvider(rosters={10001: [_roster_row(20001, "1", "2025-06-01")]})
    for _ in range(2):
        report = await sync_released_issues(
            async_db, user_id=user.id, as_of=FIXED_AS_OF, client=provider
        )
        assert report.success
        assert report.excluded_sources == report.skipped_sources == 1
        assert report.created_issues == 0
        await async_db.commit()
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 0
    assert await async_db.scalar(select(func.count()).select_from(ReadingPlanIssue)) == 0
    await async_db.refresh(new_source)
    assert new_source.enabled is True
    assert new_source.last_synced_at is None


async def test_excluded_issue_skipped_but_normal_releases_still_adopt_idempotently(
    async_db: AsyncSession,
):
    """An unmapped excluded local Issue cannot acquire a provider identity as a side effect."""
    user, thread, source = await _single_source_fixture(
        async_db, username="exclude_issue", volume_id=10002
    )
    excluded = Issue(thread_id=thread.id, issue_number="1", position=1, status="read")
    async_db.add(excluded)
    await async_db.flush()
    async_db.add(CollectionExclusion(user_id=user.id, issue_id=excluded.id))
    await async_db.commit()
    provider = _FakeProvider(
        rosters={
            10002: [
                _roster_row(20002, "1", "2025-06-01"),
                _roster_row(20003, "2", "2025-06-01"),
            ]
        }
    )
    first = await sync_released_issues(
        async_db, user_id=user.id, as_of=FIXED_AS_OF, client=provider
    )
    assert first.excluded_issues == 1
    assert first.created_issues == 1
    await async_db.commit()
    second = await sync_released_issues(
        async_db, user_id=user.id, as_of=FIXED_AS_OF, client=provider
    )
    assert second.excluded_issues == 1
    assert second.created_issues == 0
    assert second.reused_issues == 1
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 2
    members = list((await async_db.scalars(select(ReadingPlanIssue.issue_id))).all())
    assert excluded.id not in members
    assert len(members) == 1
    await async_db.refresh(excluded)
    assert excluded.status == "read"
    await async_db.refresh(source)
    assert source.enabled is True


async def test_extension_itself_refuses_an_excluded_owned_issue(async_db: AsyncSession):
    """Direct extension calls must not bypass the check already present in sync."""
    user, thread, source = await _single_source_fixture(
        async_db, username="exclude_extension", volume_id=10003
    )
    issue = Issue(thread_id=thread.id, issue_number="1", position=1, status="unread")
    async_db.add(issue)
    await async_db.flush()
    async_db.add(CollectionExclusion(user_id=user.id, issue_id=issue.id))
    await async_db.commit()
    result = await extend_plans_with_issue(
        async_db, user_id=user.id, issue_id=issue.id, source_id=source.id, store_date=FIXED_AS_OF
    )
    assert result.excluded is True
    assert result.plans_extended == []
    assert await async_db.scalar(select(func.count()).select_from(ReadingPlanIssue)) == 0


async def test_exclusion_added_while_provider_fetches_is_seen_before_insert(async_db: AsyncSession):
    """Source snapshots taken before provider I/O cannot freeze collection permission."""
    user, _, _ = await _single_source_fixture(
        async_db, username="exclude_fetch_race", volume_id=10004
    )
    await async_db.commit()

    class ExcludingProvider(_FakeProvider):
        async def fetch_volume_issues(self, volume_id: int, *, refresh: bool = False):
            async_db.add(
                CollectionExclusion(
                    user_id=user.id, provider="comicvine", external_volume_id=str(volume_id)
                )
            )
            await async_db.flush()
            return [_roster_row(20004, "1", "2025-06-01")]

    report = await sync_released_issues(
        async_db, user_id=user.id, as_of=FIXED_AS_OF, client=ExcludingProvider()
    )
    assert report.excluded_sources == 1
    assert report.created_issues == 0
    assert await async_db.scalar(select(func.count()).select_from(Issue)) == 0


async def test_disabling_during_fetch_preserves_reader_state(async_db: AsyncSession):
    """An enabled subscription snapshot is rechecked after asynchronous provider I/O."""
    user, _, source = await _single_source_fixture(
        async_db, username="disable_fetch_race", volume_id=10005
    )
    await async_db.commit()

    class DisablingProvider(_FakeProvider):
        async def fetch_volume_issues(self, volume_id: int, *, refresh: bool = False):
            source.enabled = False
            await async_db.flush()
            return [_roster_row(20005, "1", "2025-06-01")]

    report = await sync_released_issues(
        async_db, user_id=user.id, as_of=FIXED_AS_OF, client=DisablingProvider()
    )
    assert report.skipped_sources == 1
    assert report.created_issues == 0
    assert source.enabled is False
    assert source.last_synced_at is None


async def test_sync_extension_never_commits_outside_its_caller(
    async_db_committed: AsyncSession,
    db_engine: AsyncEngine,
):
    """Rollback removes adoption and extension together, preserving exclusion-lock lifetime."""
    db = async_db_committed
    user, thread, source = await _single_source_fixture(
        db, username="sync_rollback", volume_id=10006
    )
    user_id, thread_id, source_id = user.id, thread.id, source.id
    await db.commit()
    provider = _FakeProvider(rosters={10006: [_roster_row(20006, "1", "2025-06-01")]})
    report = await sync_released_issues(db, user_id=user_id, as_of=FIXED_AS_OF, client=provider)
    assert report.created_issues == 1
    verifier = async_sessionmaker(db_engine, expire_on_commit=False)
    async with verifier() as fresh:
        assert (
            await fresh.scalar(
                select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
            )
            == 0
        )
    await db.rollback()
    async with verifier() as fresh:
        assert (
            await fresh.scalar(
                select(func.count()).select_from(Issue).where(Issue.thread_id == thread_id)
            )
            == 0
        )
        assert await fresh.scalar(select(func.count()).select_from(ReadingPlanIssue)) == 0
    # The pre-existing subscription is retained, not disabled or removed by rollback.
    from app.models.reading_plan_release_source import ReadingPlanReleaseSource

    saved = await db.get(ReadingPlanReleaseSource, source_id)
    assert saved is not None and saved.enabled


async def test_another_readers_exclusion_does_not_hide_a_permitted_release(async_db: AsyncSession):
    """External volume identities are shared; reader intent is always owner scoped."""
    user, _, _ = await _single_source_fixture(async_db, username="permitted_owner", volume_id=10007)
    other = await get_or_create_user_async(async_db, "excluded_other_owner")
    async_db.add(
        CollectionExclusion(user_id=other.id, provider="comicvine", external_volume_id="10007")
    )
    await async_db.commit()
    report = await sync_released_issues(
        async_db,
        user_id=user.id,
        as_of=FIXED_AS_OF,
        client=_FakeProvider(rosters={10007: [_roster_row(20007, "1", "2025-06-01")]}),
    )
    assert report.created_issues == 1
    assert report.excluded_sources == report.excluded_issues == 0


async def test_explicit_thread_exclusion_never_disables_its_subscription(async_db: AsyncSession):
    """Sync skips an excluded target while preserving the independent Follow decision."""
    user, thread, source = await _single_source_fixture(
        async_db, username="excluded_thread", volume_id=10008
    )
    async_db.add(CollectionExclusion(user_id=user.id, thread_id=thread.id))
    await async_db.commit()
    report = await sync_released_issues(
        async_db,
        user_id=user.id,
        as_of=FIXED_AS_OF,
        client=_FakeProvider(rosters={10008: [_roster_row(20008, "1", "2025-06-01")]}),
    )
    assert report.excluded_sources == report.skipped_sources == 1
    assert report.created_issues == 0
    await async_db.refresh(source)
    assert source.enabled is True
    assert source.last_synced_at is None
