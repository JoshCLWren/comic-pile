"""Focused contract tests for the shared comic catalog API."""

from sqlalchemy import select, func

import pytest
from httpx import AsyncClient

from app.external_identities import upsert_external_identity, link_thread_external_series, link_issue_external_identity
from app.models import Issue, Thread, User
from app.models.external_identity import ExternalIdentity, IssueExternalIdentityMapping, ThreadExternalSeriesMapping
from app.schemas.catalog import (
    ExternalIdentityUpsert,
    ExternalIdentityResponse,
    ThreadSeriesAttachRequest,
    ThreadSeriesAttachResponse,
    IssueAttachRequest,
    IssueAttachResponse,
    CatalogSeriesSearchResponse,
    CatalogIssueSearchResponse,
    ThreadExternalSeriesMappingResponse,
    IssueExternalIdentityMappingResponse,
)


@pytest.mark.asyncio
async def test_catalog_series_upsert_is_idempotent(async_db: AsyncSession) -> None:
    """Idempotent upsert preserves freshest provider metadata and returns existing identity."""
    fresh = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league",
        metadata_json={"name": "Justice League"},
    )
    repeated = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league",
        metadata_json={"name": "Justice League (updated)"},
    )

    assert repeated.id == fresh.id
    assert repeated.metadata_json == {"name": "Justice League"}
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


@pytest.mark.asyncio
async def test_catalog_issue_upsert_is_idempotent(async_db: AsyncSession) -> None:
    """Idempotent upsert preserves freshest provider metadata and returns existing identity."""
    fresh = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-12345",
        metadata_json={"issue_number": "1", "name": "Test Issue"},
    )
    repeated = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-12345",
        metadata_json={"issue_number": "1", "name": "Test Issue (updated)"},
    )

    assert repeated.id == fresh.id
    assert repeated.metadata_json == {"issue_number": "1", "name": "Test Issue"}
    assert await async_db.scalar(select(func.count()).select_from(ExternalIdentity)) == 1


@pytest.mark.asyncio
async def test_search_catalog_series(async_db: AsyncSession) -> None:
    """Search catalog series by external_id."""
    await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league",
        metadata_json={"name": "Justice League"},
    )
    await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-x-men",
        metadata_json={"name": "X-Men"},
    )

    results = await async_db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.entity_type == "series",
            ExternalIdentity.provider == "comicvine",
        )
    )
    identities = results.scalars().unique().all()
    assert len(identities) == 2


@pytest.mark.asyncio
async def test_search_catalog_issues(async_db: AsyncSession) -> None:
    """Search catalog issues by external_id."""
    await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-12345",
        metadata_json={"issue_number": "1"},
    )
    await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-67890",
        metadata_json={"issue_number": "2"},
    )

    results = await async_db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.entity_type == "issue",
            ExternalIdentity.provider == "comicvine",
        )
    )
    identities = results.scalars().unique().all()
    assert len(identities) == 2


@pytest.mark.asyncio
async def test_attach_series_to_thread(async_db: AsyncSession) -> None:
    """Attach a series identity to a user's reading thread."""
    owner, thread, issue = _owned_issue(
        async_db,
        username="catalog_test_owner",
        title="Justice League",
    )

    # First upsert the series
    identity = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league",
    )

    mapping = await link_thread_external_series(
        db=async_db,
        user_id=owner.id,
        thread_id=thread.id,
        external_identity_id=identity.id,
        status="confirmed",
        evidence_source="cbl:justice-league",
        confidence=1.0,
    )

    assert mapping.status == "confirmed"
    assert mapping.evidence_source == "cbl:justice-league"
    assert mapping.confidence == 1.0


@pytest.mark.asyncio
async def test_attach_issue_to_thread(async_db: AsyncSession) -> None:
    """Attach an issue identity to a user's reading thread."""
    owner, thread, issue = _owned_issue(
        async_db,
        username="catalog_issue_test_owner",
        title="Test Series",
        issue_number="1",
    )

    # First upsert the issue
    identity = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-12345",
    )

    mapping = await link_issue_external_identity(
        db=async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=identity.id,
        status="confirmed",
        evidence_source="cbl:test-mapping",
        confidence=0.95,
    )

    assert mapping.status == "confirmed"
    assert mapping.evidence_source == "cbl:test-mapping"
    assert mapping.confidence == 0.95


@pytest.mark.asyncio
async def test_list_series_mappings(async_db: AsyncSession) -> None:
    """List thread-series mappings (inspection endpoint)."""
    owner, thread, issue = _owned_issue(
        async_db,
        username="catalog_mapping_list_owner",
        title="Test Series",
    )

    # Create a series mapping
    series_identity = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="series",
        external_id="4050-justice-league",
    )
    await link_thread_external_series(
        db=async_db,
        user_id=owner.id,
        thread_id=thread.id,
        external_identity_id=series_identity.id,
        status="confirmed",
    )

    # List mappings
    result = await async_db.execute(
        select(ThreadExternalSeriesMapping).where(
            ThreadExternalSeriesMapping.thread_id == thread.id
        )
    )
    mappings = result.scalars().all()
    assert len(mappings) == 1
    assert mappings[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_issue_mappings(async_db: AsyncSession) -> None:
    """List issue-external identity mappings (inspection endpoint)."""
    owner, thread, issue = _owned_issue(
        async_db,
        username="catalog_issue_list_owner",
        title="Test Series",
        issue_number="1",
    )

    # Create an issue mapping
    issue_identity = await upsert_external_identity(
        async_db,
        provider="comicvine",
        entity_type="issue",
        external_id="4000-12345",
    )
    await link_issue_external_identity(
        db=async_db,
        user_id=owner.id,
        issue_id=issue.id,
        external_identity_id=issue_identity.id,
        status="confirmed",
        evidence_source="cbl:test",
        confidence=0.9,
    )

    # List mappings
    result = await async_db.execute(
        select(IssueExternalIdentityMapping).where(
            IssueExternalIdentityMapping.issue_id == issue.id
        )
    )
    mappings = result.scalars().all()
    assert len(mappings) == 1
    assert mappings[0].status == "confirmed"


async def _owned_issue(
    db: AsyncSession,
    *,
    username: str,
    title: str,
    issue_number: str = "1",
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