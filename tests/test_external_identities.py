"""Contract tests for provider-independent external comic identities."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.external_identities import (
    ExternalIdentityMappingError,
    link_issue_external_identity,
    link_thread_external_series,
    upsert_external_identity,
)
from app.models import Issue, Thread, User
from app.models.external_identity import (
    ExternalIdentity,
    IssueExternalIdentityMapping,
    ThreadExternalSeriesMapping,
)


async def _owned_issue(db: AsyncSession, *, username: str, title: str, issue_number: str = "1") -> tuple[User, Thread, Issue]:
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
    assert await async_db.scalar(
        select(func.count()).select_from(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    ) == 3

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
    assert await async_db.scalar(
        select(func.count()).select_from(ThreadExternalSeriesMapping).where(
            ThreadExternalSeriesMapping.thread_id == thread.id,
            ThreadExternalSeriesMapping.status == "confirmed",
        )
    ) == 2


@pytest.mark.asyncio
async def test_deleting_external_evidence_never_deletes_user_owned_reading_data(
    async_db: AsyncSession,
) -> None:
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
    assert await async_db.scalar(
        select(func.count()).select_from(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.external_identity_id == identity_id
        )
    ) == 0
