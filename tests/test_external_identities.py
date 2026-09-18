"""Contract tests for provider-independent external comic identities."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.external_identities import (
    ExternalIdentityMappingError,
    ExternalIdentitySpec,
    link_issue_external_identity,
    link_thread_external_series,
    upsert_external_identities,
    upsert_external_identity,
)
from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)


async def _owned_issue(
    db: AsyncSession, *, username: str, title: str, issue_number: str = "1"
) -> tuple[User, Thread, Issue]:
    user = User(username=username)
    db.add(user)
    await db.flush()
    thread = Thread(
        title=title,
        format="Comic",
        issues_remaining=1,
        queue_position=1,
        status="active",
        user_id=user.id,
    )
    db.add(thread)
    await db.flush()
    issue = Issue(thread_id=thread.id, issue_number=issue_number, position=1)
    db.add(issue)
    await db.flush()
    return user, thread, issue


@pytest.mark.asyncio
async def test_external_identity_upsert_is_idempotent_and_rejects_stale_provider_evidence(
    async_db: AsyncSession,
) -> None:
    """Idempotent upsert preserves freshest provider metadata and rejects stale evidence."""
    fresh_at = datetime.now(UTC)
    fresh = await upsert_external_identity(
        async_db,
        provider=" ComicVine ",
        entity_type="issue",
        external_id="4000-12345",
        external_url="https://comicvine.gamespot.com/issue/fresh/",
        metadata_json={"name": "Fresh title"},
        provider_updated_at=fresh_at,
    )
    repeated = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id=" 4000-12345 ",
        external_url="https://comicvine.gamespot.com/issue/stale/",
        metadata_json={"name": "Stale title"},
        provider_updated_at=fresh_at - timedelta(days=1),
    )

    assert repeated.id == fresh.id
    assert repeated.external_url == "https://comicvine.gamespot.com/issue/fresh/"
    assert repeated.metadata_json == {"name": "Fresh title"}
    assert repeated.provider_updated_at == fresh_at
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1

    cbl = await upsert_external_identity(
        async_db,
        provider="cbl",
        entity_type="series",
        external_id="reading-list:x-men/messiah-complex",
        metadata_json={"source": "CBL-ReadingLists"},
    )
    assert cbl.provider == "cbl"
    assert cbl.entity_type == "series"


@pytest.mark.asyncio
async def test_issue_mapping_preserves_candidates_rejections_and_user_ownership(
    async_db: AsyncSession,
) -> None:
    """Candidate, confirmed, rejected states preserved; ownership enforced; provider conflict blocked."""
    owner, _thread, issue = await _owned_issue(
        async_db,
        username="external_identity_owner",
        title="The Power of SHAZAM!",
        issue_number="Annual 1",
    )
    other_user = User(username="external_identity_other")
    async_db.add(other_user)
    await async_db.flush()

    winner = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="4000-annual"
    )
    ambiguous = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="4000-ambiguous"
    )
    rejected = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="4000-rejected"
    )

    winner_mapping = await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=winner.id,
        status="confirmed",
        evidence_source="cbl:power-of-shazam",
        confidence=1.0,
    )
    repeated = await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=winner.id,
        status="confirmed",
        evidence_source="cbl:power-of-shazam",
        confidence=1.0,
    )
    await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=ambiguous.id,
        status="candidate",
        confidence=0.55,
    )
    rejected_mapping = await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=rejected.id,
        status="rejected",
        rejection_reason="Wrong annual despite similar title",
    )

    assert repeated.id == winner_mapping.id
    assert rejected_mapping.rejection_reason == "Wrong annual despite similar title"
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(IssueExternalIdentityMapping)
            .where(IssueExternalIdentityMapping.issue_id == issue.id)
        )
        == 3
    )

    with pytest.raises(ExternalIdentityMappingError, match="not owned"):
        await link_issue_external_identity(
            async_db,
            user_id=other_user.id,
            issue_id=issue.id,
            external_identity_id=winner.id,
            status="confirmed",
        )

    with pytest.raises(ExternalIdentityMappingError, match="already has a confirmed"):
        await link_issue_external_identity(
            async_db,
            user_id=owner.id,
            issue_id=issue.id,
            external_identity_id=ambiguous.id,
            status="confirmed",
        )


@pytest.mark.asyncio
async def test_composite_thread_supports_multiple_series_and_issue_mapping_survives_title_change(
    async_db: AsyncSession,
) -> None:
    """Thread can link multiple confirmed series; issue mapping survives thread title change."""
    owner, thread, issue = await _owned_issue(
        async_db,
        username="external_identity_composite",
        title="Justice League America",
    )
    first_volume = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="series", external_id="4050-justice-league"
    )
    second_volume = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league-international",
    )
    issue_identity = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="4000-jla-1"
    )

    first_mapping = await link_thread_external_series(
        async_db,
        user_id=owner.id,
        thread_id=thread.id,
        external_identity_id=first_volume.id,
        status="confirmed",
    )
    second_mapping = await link_thread_external_series(
        async_db,
        user_id=owner.id,
        thread_id=thread.id,
        external_identity_id=second_volume.id,
        status="confirmed",
    )
    issue_mapping = await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=issue_identity.id,
        status="confirmed",
    )

    thread.title = "JLI / JLA reading project"
    await async_db.flush()

    assert first_mapping.thread_id == second_mapping.thread_id == thread.id
    assert first_mapping.external_identity_id != second_mapping.external_identity_id
    assert issue_mapping.issue_id == issue.id
    assert issue.thread_id == thread.id
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(ThreadExternalSeriesMapping)
            .where(
                ThreadExternalSeriesMapping.thread_id == thread.id,
                ThreadExternalSeriesMapping.status == "confirmed",
            )
        )
        == 2
    )


@pytest.mark.asyncio
async def test_deleting_external_evidence_never_deletes_user_owned_reading_data(
    async_db: AsyncSession,
) -> None:
    """Deleting external identity cascades only mappings; user threads/issues remain intact."""
    owner, thread, issue = await _owned_issue(
        async_db,
        username="external_identity_delete_safety",
        title="B.P.R.D.: War on Frogs",
        issue_number="Revival",
    )
    identity = await upsert_external_identity(
        async_db, provider="comicvine", entity_type="issue", external_id="4000-revival"
    )
    await link_issue_external_identity(
        async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=identity.id,
        status="confirmed",
    )
    identity_id = identity.id

    await async_db.delete(identity)
    await async_db.flush()

    assert await async_db.get(Thread, thread.id) is not None
    assert await async_db.get(Issue, issue.id) is not None
    assert (
        await async_db.scalar(
            select(func.count())
            .select_from(IssueExternalIdentityMapping)
            .where(IssueExternalIdentityMapping.external_identity_id == identity_id)
        )
        == 0
    )


@pytest.mark.asyncio
async def test_upsert_external_identities_batches_and_deduplicates(
    async_db: AsyncSession,
) -> None:
    """Batch upsert creates multiple identities in one round trip and deduplicates."""
    specs = [
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-series-1",
        ),
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="issue",
            external_id="4000-issue-1",
        ),
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-series-2",
        ),
        # Duplicate spec should be deduplicated
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-series-1",
        ),
    ]

    result = await upsert_external_identities(async_db, specs=specs)

    assert len(result) == 3
    assert ("comicvine", "series", "4050-series-1") in result
    assert ("comicvine", "issue", "4000-issue-1") in result
    assert ("comicvine", "series", "4050-series-2") in result

    # Verify all three identities were created
    count = await async_db.scalar(select(func.count()).select_from(ExternalIdentity))
    assert count == 3

    # Second call with same specs should be idempotent
    result2 = await upsert_external_identities(async_db, specs=specs)
    assert len(result2) == 3
    assert (
        result2[("comicvine", "series", "4050-series-1")].id
        == result[("comicvine", "series", "4050-series-1")].id
    )

    count2 = await async_db.scalar(select(func.count()).select_from(ExternalIdentity))
    assert count2 == 3


@pytest.mark.asyncio
async def test_upsert_external_identities_updates_fresh_metadata(
    async_db: AsyncSession,
) -> None:
    """Batch upsert updates metadata when provider_updated_at is fresher."""
    fresh_at = datetime.now(UTC)
    stale_at = fresh_at - timedelta(days=1)

    # Create initial identities with stale metadata
    specs = [
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-meta-test",
            external_url="https://example.com/stale",
            metadata_json={"name": "Stale"},
            provider_updated_at=stale_at,
        ),
    ]
    await upsert_external_identities(async_db, specs=specs)

    # Update with fresh metadata
    fresh_specs = [
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-meta-test",
            external_url="https://example.com/fresh",
            metadata_json={"name": "Fresh"},
            provider_updated_at=fresh_at,
        ),
    ]
    result = await upsert_external_identities(async_db, specs=fresh_specs)

    identity = result[("comicvine", "series", "4050-meta-test")]
    assert identity.external_url == "https://example.com/fresh"
    assert identity.metadata_json == {"name": "Fresh"}
    assert identity.provider_updated_at == fresh_at

    # Stale update should be ignored
    stale_specs = [
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-meta-test",
            external_url="https://example.com/stale-again",
            metadata_json={"name": "Stale Again"},
            provider_updated_at=stale_at,
        ),
    ]
    result2 = await upsert_external_identities(async_db, specs=stale_specs)

    identity2 = result2[("comicvine", "series", "4050-meta-test")]
    assert identity2.external_url == "https://example.com/fresh"
    assert identity2.metadata_json == {"name": "Fresh"}
    assert identity2.provider_updated_at == fresh_at


@pytest.mark.asyncio
async def test_upsert_external_identities_rejects_invalid_specs(
    async_db: AsyncSession,
) -> None:
    """Batch upsert validates all specs before any persistence."""
    specs = [
        ExternalIdentitySpec(
            provider="comicvine",
            entity_type="series",
            external_id="4050-valid",
        ),
        ExternalIdentitySpec(
            provider="",  # Invalid: empty provider
            entity_type="issue",
            external_id="4000-invalid",
        ),
    ]

    with pytest.raises(ExternalIdentityMappingError, match="provider and external_id are required"):
        await upsert_external_identities(async_db, specs=specs)

    # No partial writes should have occurred
    count = await async_db.scalar(select(func.count()).select_from(ExternalIdentity))
    assert count == 0


@pytest.mark.asyncio
async def test_upsert_external_identities_empty_iterable(
    async_db: AsyncSession,
) -> None:
    """Empty iterable returns empty mapping without database access."""
    result = await upsert_external_identities(async_db, specs=[])
    assert result == {}


@pytest.mark.asyncio
async def test_batch_upsert_converges_when_concurrent_writer_committed_same_identity(
    db_engine: AsyncEngine,
) -> None:
    """Batch upsert converges to a committed identity instead of raising or cloning it."""
    winner_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async with winner_factory() as winner_db:
        competing = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id="4050-concurrent-series",
            metadata_json={"name": "Winner"},
        )
        winner_db.add(competing)
        await winner_db.commit()
        winner_id = competing.id

    async with winner_factory() as caller_db:
        async with caller_db.begin():
            result = await upsert_external_identities(
                caller_db,
                specs=[
                    # No metadata here: provided metadata overwrites per the
                    # single-upsert merge contract (see the fresh/stale test).
                    # This test proves race convergence, not clobbering.
                    ExternalIdentitySpec(
                        provider="comicvine",
                        entity_type="series",
                        external_id="4050-concurrent-series",
                    ),
                    ExternalIdentitySpec(
                        provider="comicvine",
                        entity_type="issue",
                        external_id="4000-concurrent-issue",
                    ),
                ],
            )

            assert ("comicvine", "series", "4050-concurrent-series") in result
            assert ("comicvine", "issue", "4000-concurrent-issue") in result
            assert result[("comicvine", "series", "4050-concurrent-series")].id == winner_id
            assert result[("comicvine", "series", "4050-concurrent-series")].metadata_json == {
                "name": "Winner"
            }

            other = ExternalIdentity(
                provider="comicvine",
                entity_type="issue",
                external_id="4000-sibling",
            )
            caller_db.add(other)
            await caller_db.flush()

        count = await caller_db.scalar(select(func.count()).select_from(ExternalIdentity))
        assert count == 3
        survivor = await caller_db.scalar(
            select(ExternalIdentity).where(ExternalIdentity.external_id == "4050-concurrent-series")
        )
        assert survivor is not None
        assert survivor.id == winner_id
        assert survivor.metadata_json == {"name": "Winner"}
