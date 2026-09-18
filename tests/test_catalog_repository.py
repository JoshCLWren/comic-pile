"""Tests for catalog repository functions."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external_identity import ExternalIdentity
from app.repositories.catalog_repository import (
    search_catalog_series,
    search_catalog_issues,
    list_series_mappings,
    list_issue_mappings,
)


@pytest.mark.asyncio
async def test_search_catalog_series_no_search(db: AsyncSession, sample_data):
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
    db.add_all([series1, series2])
    await db.commit()

    # Search without query should return all series (up to limit)
    result = await search_catalog_series(db, provider="comicvine", limit=10)
    assert len(result) == 2
    assert all(r.entity_type == "series" for r in result)
    assert all(r.provider == "comicvine" for r in result)


@pytest.mark.asyncio
async def test_search_catalog_series_with_search(db: AsyncSession, sample_data):
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
        external_id="2000-another-series",
        external_url="https://comicvine.com/2000-another-series",
        metadata_json={"name": "Another Test Series"},
    )
    db.add_all([series1, series2])
    await db.commit()

    # Search with "test" should return only matching series
    result = await search_catalog_series(db, search="test", provider="comicvine", limit=10)
    assert len(result) == 2  # Both contain "test"
    
    # Search with "another" should return only one
    result = await search_catalog_series(db, search="another", provider="comicvine", limit=10)
    assert len(result) == 1
    assert result[0].external_id == "2000-another-series"


@pytest.mark.asyncio
async def test_search_catalog_series_respects_limit(db: AsyncSession, sample_data):
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
    db.add_all(series_list)
    await db.commit()

    # Search with limit should return at most that many results
    result = await search_catalog_series(db, limit=3)
    assert len(result) <= 3


@pytest.mark.asyncio
async def test_search_catalog_issues_with_series_filter(db: AsyncSession, sample_data):
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
    db.add_all([series, issue1, issue2])
    await db.commit()

    # Search issues with series filter should return issues for that series
    result = await search_catalog_issues(
        db, 
        series_external_id="1000-test-series", 
        provider="comicvine", 
        limit=10
    )
    assert len(result) == 0  # No direct relationship in this test data
    
    # Search without series filter should return all issues
    result = await search_catalog_issues(db, provider="comicvine", limit=10)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_search_catalog_issues_nonexistent_series(db: AsyncSession, sample_data):
    """Test searching catalog issues with non-existent series returns empty."""
    # Search with non-existent series should return empty list
    result = await search_catalog_issues(
        db, 
        series_external_id="nonexistent-series", 
        provider="comicvine", 
        limit=10
    )
    assert len(result) == 0


@pytest.mark.asyncio
async def test_list_series_mappings_with_filters(db: AsyncSession, sample_data):
    """Test listing series mappings with optional filters."""
    from app.models.external_identity import ThreadExternalSeriesMapping
    
    # Add test mappings
    mapping1 = ThreadExternalSeriesMapping(
        thread_id=1,
        external_identity_id=1,
        status="confirmed",
    )
    mapping2 = ThreadExternalSeriesMapping(
        thread_id=2,
        external_identity_id=2,
        status="candidate",
    )
    db.add_all([mapping1, mapping2])
    await db.commit()

    # List all mappings
    result = await list_series_mappings(db, limit=10)
    assert len(result) >= 2
    
    # Filter by thread_id
    result = await list_series_mappings(db, thread_id=1, limit=10)
    assert len(result) == 1
    assert result[0].thread_id == 1
    
    # Filter by status
    result = await list_series_mappings(db, status="confirmed", limit=10)
    assert len(result) == 1
    assert result[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_issue_mappings_with_filters(db: AsyncSession, sample_data):
    """Test listing issue mappings with optional filters."""
    from app.models.external_identity import IssueExternalIdentityMapping
    
    # Add test mappings
    mapping1 = IssueExternalIdentityMapping(
        issue_id=1,
        external_identity_id=1,
        status="confirmed",
    )
    mapping2 = IssueExternalIdentityMapping(
        issue_id=2,
        external_identity_id=2,
        status="rejected",
    )
    db.add_all([mapping1, mapping2])
    await db.commit()

    # List all mappings
    result = await list_issue_mappings(db, limit=10)
    assert len(result) >= 2
    
    # Filter by issue_id
    result = await list_issue_mappings(db, issue_id=1, limit=10)
    assert len(result) == 1
    assert result[0].issue_id == 1
    
    # Filter by status
    result = await list_issue_mappings(db, status="confirmed", limit=10)
    assert len(result) == 1
    assert result[0].status == "confirmed"


@pytest.mark.asyncio
async def test_list_mappings_respects_limit(db: AsyncSession, sample_data):
    """Test that list mappings functions respect the hard limit."""
    from app.models.external_identity import ThreadExternalSeriesMapping, IssueExternalIdentityMapping
    
    # Add multiple mappings
    for i in range(10):
        mapping = ThreadExternalSeriesMapping(
            thread_id=i,
            external_identity_id=i,
            status="confirmed",
        )
        db.add(mapping)
    
    for i in range(10):
        mapping = IssueExternalIdentityMapping(
            issue_id=i,
            external_identity_id=i,
            status="confirmed",
        )
        db.add(mapping)
    
    await db.commit()

    # List should respect limit
    result = await list_series_mappings(db, limit=3)
    assert len(result) <= 3
    
    result = await list_issue_mappings(db, limit=3)
    assert len(result) <= 3
