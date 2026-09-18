"""Tests for catalog repository functions."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue
from app.models.external_identity import ExternalIdentity
from app.repositories.catalog_repository import (
    search_catalog_series,
    search_catalog_issues,
    list_series_mappings,
    list_issue_mappings,
)


@pytest.mark.asyncio
async def test_search_catalog_series_no_search(async_db: AsyncSession, sample_data):
    """Test searching catalog series without search term returns all series."""
    # Add test series data
    series1 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="1000-test-series",
        external_url="https://comicvine.com/1000-test-series",
        metadata_json={"name": "Test Series 1"},
    )
    series2 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="2000-another-series",
        external_url="https://comicvine.com/2000-another-series",
        metadata_json={"name": "Test Series 2"},
    )
    async_db.add_all([series1, series2])
    await async_db.commit()

    # Search without query should return all series (up to limit)
    result = await search_catalog_series(async_db, provider="comicvine", limit=10)
    assert len(result) == 2
    assert all(r.entity_type == "series" for r in result)
    assert all(r.provider == "comicvine" for r in result)


@pytest.mark.asyncio
async def test_search_catalog_series_with_search(async_db: AsyncSession, sample_data):
    """Test searching catalog series with search term filters results."""
    # Add test series data
    series1 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="1000-test-series",
        external_url="https://comicvine.com/1000-test-series",
        metadata_json={"name": "Test Series 1"},
    )
    series2 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="2000-another-test-series",
        external_url="https://comicvine.com/2000-another-test-series",
        metadata_json={"name": "Another Test Series"},
    )
    async_db.add_all([series1, series2])
    await async_db.commit()

    # Search with "test" should return only matching series
    result = await search_catalog_series(async_db, search="test", provider="comicvine", limit=10)
    assert len(result) == 2  # Both external_ids contain "test"

    # Search with "another" should return only one
    result = await search_catalog_series(async_db, search="another", provider="comicvine", limit=10)
    assert len(result) == 1
    assert result[0].external_id == "2000-another-test-series"


@pytest.mark.asyncio
async def test_search_catalog_series_respects_limit(async_db: AsyncSession, sample_data):
    """Test that catalog series search respects the hard limit."""
    # Add multiple series
    series_list = []
    for i in range(10):
        series = ExternalIdentity(
            provider="comicvine",
            entity_type="series",
            external_id=f"{i}-test-series",
            metadata_json={"name": f"Test Series {i}"},
        )
        series_list.append(series)
    async_db.add_all(series_list)
    await async_db.commit()

    # Search with limit should return at most that many results
    result = await search_catalog_series(async_db, limit=3)
    assert len(result) <= 3


@pytest.mark.asyncio
async def test_search_catalog_issues_with_series_filter(async_db: AsyncSession, sample_data):
    """Test searching catalog issues with series external ID filter."""
    # Add test series and issue data
    series = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="1000-test-series",
        metadata_json={"name": "Test Series"},
    )
    issue1 = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="1001-issue-1",
        metadata_json={"name": "Issue 1"},
    )
    issue2 = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="1002-issue-2",
        metadata_json={"name": "Issue 2"},
    )
    async_db.add_all([series, issue1, issue2])
    await async_db.commit()

    # The series exists, so issues remain queryable. The catalog has no
    # series-to-issue foreign key relationship, so the series external_id acts
    # as an existence gate rather than scoping the issue results.
    result = await search_catalog_issues(
        async_db, 
        series_external_id="1000-test-series", 
        provider="comicvine", 
        limit=10
    )
    assert len(result) == 2
    
    # Search without series filter should return all issues
    result = await search_catalog_issues(async_db, provider="comicvine", limit=10)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_catalog_issues_nonexistent_series(async_db: AsyncSession, sample_data):
    """Test searching catalog issues with non-existent series returns empty."""
    # Search with non-existent series should return empty list
    result = await search_catalog_issues(
        async_db, 
        series_external_id="nonexistent-series", 
        provider="comicvine", 
        limit=10
    )
    assert len(result) == 0


@pytest.mark.asyncio
async def test_list_series_mappings_with_filters(async_db: AsyncSession, sample_data):
    """Test listing series mappings with optional filters."""
    from app.models.external_identity import ThreadExternalSeriesMapping
    
    # Add test mappings
    identity1 = ExternalIdentity(provider="comicvine", entity_type="series", external_id="s1")
    identity2 = ExternalIdentity(provider="comicvine", entity_type="series", external_id="s2")
    async_db.add_all([identity1, identity2])
    await async_db.flush()

    mapping1 = ThreadExternalSeriesMapping(
        thread_id=sample_data["threads"][0].id,
        external_identity_id=identity1.id,
        status="confirmed",
    )
    mapping2 = ThreadExternalSeriesMapping(
        thread_id=sample_data["threads"][1].id,
        external_identity_id=identity2.id,
        status="candidate",
    )
    async_db.add_all([mapping1, mapping2])
    await async_db.commit()

    # List all mappings
    result = await list_series_mappings(async_db, limit=10)
    assert len(result) >= 2
    
    # Filter by thread_id
    result = await list_series_mappings(async_db, thread_id=sample_data["threads"][0].id, limit=10)
    assert len(result) == 1
    assert result[0].thread_id == sample_data["threads"][0].id
    
    # Filter by status
    result = await list_series_mappings(async_db, status="confirmed", limit=10)
    assert len(result) == 1
    assert result[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_issue_mappings_with_filters(async_db: AsyncSession, sample_data):
    """Test listing issue mappings with optional filters."""
    from app.models.external_identity import IssueExternalIdentityMapping
    
    issues = (
        await async_db.execute(
            select(Issue)
            .where(Issue.thread_id == sample_data["threads"][1].id)
            .order_by(Issue.id)
        )
    ).scalars().all()

    # Add test mappings
    identity1 = ExternalIdentity(provider="comicvine", entity_type="issue", external_id="i1")
    identity2 = ExternalIdentity(provider="comicvine", entity_type="issue", external_id="i2")
    async_db.add_all([identity1, identity2])
    await async_db.flush()

    mapping1 = IssueExternalIdentityMapping(
        issue_id=issues[0].id,
        external_identity_id=identity1.id,
        status="confirmed",
    )
    mapping2 = IssueExternalIdentityMapping(
        issue_id=issues[1].id,
        external_identity_id=identity2.id,
        status="rejected",
    )
    async_db.add_all([mapping1, mapping2])
    await async_db.commit()

    # List all mappings
    result = await list_issue_mappings(async_db, limit=10)
    assert len(result) >= 2
    
    # Filter by issue_id
    result = await list_issue_mappings(async_db, issue_id=issues[0].id, limit=10)
    assert len(result) == 1
    assert result[0].issue_id == issues[0].id
    
    # Filter by status
    result = await list_issue_mappings(async_db, status="confirmed", limit=10)
    assert len(result) == 1
    assert result[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_mappings_respects_limit(async_db: AsyncSession, sample_data):
    """Test that list mappings functions respect the hard limit."""
    from app.models.external_identity import ThreadExternalSeriesMapping, IssueExternalIdentityMapping
    
    # Add multiple mappings
    thread_id = sample_data["threads"][0].id
    issues = (
        await async_db.execute(
            select(Issue)
            .where(Issue.thread_id == sample_data["threads"][1].id)
            .order_by(Issue.id)
        )
    ).scalars().all()
    issue_id = issues[0].id

    for i in range(10):
        identity = ExternalIdentity(provider="comicvine", entity_type="series", external_id=f"s{i}")
        async_db.add(identity)
        await async_db.flush()
        mapping = ThreadExternalSeriesMapping(
            thread_id=thread_id,
            external_identity_id=identity.id,
            status="confirmed",
        )
        async_db.add(mapping)
    
    for i in range(10):
        identity = ExternalIdentity(provider="comicvine", entity_type="issue", external_id=f"i{i}")
        async_db.add(identity)
        await async_db.flush()
        mapping = IssueExternalIdentityMapping(
            issue_id=issue_id,
            external_identity_id=identity.id,
            status="confirmed",
        )
        async_db.add(mapping)
    
    await async_db.commit()

    # List should respect limit
    result = await list_series_mappings(async_db, limit=3)
    assert len(result) <= 3

    result = await list_issue_mappings(async_db, limit=3)
    assert len(result) <= 3
