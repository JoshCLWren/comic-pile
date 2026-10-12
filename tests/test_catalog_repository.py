"""Tests for catalog repository functions."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Issue
from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import ExternalIdentity
from app.repositories.catalog_repository import (
    get_catalog_issue_by_external_identity,
    get_catalog_issue_by_id,
    get_catalog_series_by_external_identity,
    get_catalog_series_by_id,
    get_or_create_catalog_issue,
    get_or_create_catalog_series,
    link_catalog_issue_to_series,
    list_issue_mappings,
    list_series_mappings,
    search_catalog_issues,
    search_catalog_series,
)


@pytest.mark.asyncio
async def test_get_catalog_series_by_external_identity(db: AsyncSession) -> None:
    """Test fetching a catalog series by its external identity ID."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series)
    await db.flush()

    result = await get_catalog_series_by_external_identity(db, ext_identity.id)
    assert result is not None
    assert result.id == catalog_series.id
    assert result.canonical_external_identity_id == ext_identity.id

    # Non-existent
    result = await get_catalog_series_by_external_identity(db, 99999)
    assert result is None


@pytest.mark.asyncio
async def test_get_catalog_issue_by_external_identity(db: AsyncSession) -> None:
    """Test fetching a catalog issue by its external identity ID."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    result = await get_catalog_issue_by_external_identity(db, ext_identity.id)
    assert result is not None
    assert result.id == catalog_issue.id
    assert result.canonical_external_identity_id == ext_identity.id

    result = await get_catalog_issue_by_external_identity(db, 99999)
    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_catalog_series_idempotent(db: AsyncSession) -> None:
    """Test that get_or_create_catalog_series is idempotent."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    # First call creates
    result1 = await get_or_create_catalog_series(db, canonical_external_identity_id=ext_identity.id)
    assert result1.id is not None

    # Second call returns same
    result2 = await get_or_create_catalog_series(db, canonical_external_identity_id=ext_identity.id)
    assert result2.id == result1.id

    # Third call also returns same
    result3 = await get_or_create_catalog_series(db, canonical_external_identity_id=ext_identity.id)
    assert result3.id == result1.id


@pytest.mark.asyncio
async def test_get_or_create_catalog_issue_idempotent(db: AsyncSession) -> None:
    """Test that get_or_create_catalog_issue is idempotent."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    result1 = await get_or_create_catalog_issue(db, canonical_external_identity_id=ext_identity.id)
    assert result1.id is not None

    result2 = await get_or_create_catalog_issue(db, canonical_external_identity_id=ext_identity.id)
    assert result2.id == result1.id


@pytest.mark.asyncio
async def test_get_or_create_catalog_series_concurrent_simulation(db: AsyncSession) -> None:
    """Test get_or_create_catalog_series handles concurrent inserts correctly.

    This simulates the race condition where two concurrent calls try to create
    the same catalog series. The ON CONFLICT DO NOTHING + SELECT pattern
    ensures only one row is created.
    """
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    # Simulate concurrent insert by manually inserting first, then calling get_or_create
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # First "concurrent" insert
    stmt = (
        pg_insert(CatalogSeries)
        .values(canonical_external_identity_id=ext_identity.id)
        .on_conflict_do_nothing(index_elements=[CatalogSeries.canonical_external_identity_id])
        .returning(CatalogSeries.id)
    )
    await db.execute(stmt)
    await db.flush()

    # Now call get_or_create - should fetch the existing row
    result = await get_or_create_catalog_series(db, canonical_external_identity_id=ext_identity.id)
    assert result is not None
    assert result.canonical_external_identity_id == ext_identity.id

    # Verify only one row exists
    count_result = await db.execute(
        select(CatalogSeries).where(CatalogSeries.canonical_external_identity_id == ext_identity.id)
    )
    rows = count_result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_or_create_catalog_issue_concurrent_simulation(db: AsyncSession) -> None:
    """Test get_or_create_catalog_issue handles concurrent inserts correctly."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # First "concurrent" insert
    stmt = (
        pg_insert(CatalogIssue)
        .values(canonical_external_identity_id=ext_identity.id)
        .on_conflict_do_nothing(index_elements=[CatalogIssue.canonical_external_identity_id])
        .returning(CatalogIssue.id)
    )
    await db.execute(stmt)
    await db.flush()

    # Now call get_or_create - should fetch the existing row
    result = await get_or_create_catalog_issue(db, canonical_external_identity_id=ext_identity.id)
    assert result is not None
    assert result.canonical_external_identity_id == ext_identity.id

    # Verify only one row exists
    count_result = await db.execute(
        select(CatalogIssue).where(CatalogIssue.canonical_external_identity_id == ext_identity.id)
    )
    rows = count_result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_link_catalog_issue_to_series_additive_only(db: AsyncSession) -> None:
    """Test that linking catalog issue to series is additive (only if NULL)."""
    # Create series and issue
    series_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    issue_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add_all([series_ext, issue_ext])
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=series_ext.id)
    catalog_issue = CatalogIssue(canonical_external_identity_id=issue_ext.id)
    db.add_all([catalog_series, catalog_issue])
    await db.flush()

    # First link should succeed
    result = await link_catalog_issue_to_series(
        db, catalog_issue_id=catalog_issue.id, catalog_series_id=catalog_series.id
    )
    assert result is not None
    assert result.catalog_series_id == catalog_series.id

    # Second link attempt should return None (already linked)
    result2 = await link_catalog_issue_to_series(
        db, catalog_issue_id=catalog_issue.id, catalog_series_id=catalog_series.id
    )
    assert result2 is None

    # Verify the link wasn't changed
    await db.refresh(catalog_issue)
    assert catalog_issue.catalog_series_id == catalog_series.id


@pytest.mark.asyncio
async def test_link_catalog_issue_to_series_different_series_fails(db: AsyncSession) -> None:
    """Test that linking to a different series when already linked returns None."""
    # Create two series
    series_ext1 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series 1"},
    )
    series_ext2 = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="54321",
        metadata_json={"name": "Test Series 2"},
    )
    issue_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add_all([series_ext1, series_ext2, issue_ext])
    await db.flush()

    catalog_series1 = CatalogSeries(canonical_external_identity_id=series_ext1.id)
    catalog_series2 = CatalogSeries(canonical_external_identity_id=series_ext2.id)
    catalog_issue = CatalogIssue(canonical_external_identity_id=issue_ext.id)
    db.add_all([catalog_series1, catalog_series2, catalog_issue])
    await db.flush()

    # Link to first series
    result = await link_catalog_issue_to_series(
        db, catalog_issue_id=catalog_issue.id, catalog_series_id=catalog_series1.id
    )
    assert result is not None

    # Try to link to second series - should return None (additive only)
    result2 = await link_catalog_issue_to_series(
        db, catalog_issue_id=catalog_issue.id, catalog_series_id=catalog_series2.id
    )
    assert result2 is None

    # Verify still linked to first series
    await db.refresh(catalog_issue)
    assert catalog_issue.catalog_series_id == catalog_series1.id


@pytest.mark.asyncio
async def test_link_catalog_issue_to_series_nonexistent_returns_none(db: AsyncSession) -> None:
    """Test that linking with nonexistent IDs returns None."""
    result = await link_catalog_issue_to_series(
        db, catalog_issue_id=99999, catalog_series_id=88888
    )
    assert result is None


@pytest.mark.asyncio
async def test_get_catalog_series_by_id(db: AsyncSession) -> None:
    """Test fetching catalog series by ID."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series)
    await db.flush()

    result = await get_catalog_series_by_id(db, catalog_series.id)
    assert result is not None
    assert result.id == catalog_series.id

    result = await get_catalog_series_by_id(db, 99999)
    assert result is None


@pytest.mark.asyncio
async def test_get_catalog_issue_by_id(db: AsyncSession) -> None:
    """Test fetching catalog issue by ID."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    result = await get_catalog_issue_by_id(db, catalog_issue.id)
    assert result is not None
    assert result.id == catalog_issue.id

    result = await get_catalog_issue_by_id(db, 99999)
    assert result is None


# ---------------------------------------------------------------------------
# Existing external-identity search and mapping-inspection surface.
#
# Issue #3220 is additive. The `/api/v1/catalog/*` read endpoints keep their
# pre-v1 `external_identities` semantics: they must not be narrowed to rows
# that already carry a catalog entry, because acceptance criterion 3 requires
# existing libraries to keep working with no backfill and no catalog service
# calls. These tests pin that contract so a catalog-membership requirement
# cannot silently reappear.
# ---------------------------------------------------------------------------


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
async def test_search_catalog_series_includes_identities_without_catalog_row(
    async_db: AsyncSession,
):
    """Regression: #3220 acceptance criterion 3 keeps catalog-free identities searchable.

    A pre-v1 library has no ``catalog_series`` row and no backfill populates
    one, so the search endpoint must still return it.
    """
    uncataloged = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="3000-uncataloged-series",
        metadata_json={"name": "Uncataloged Series"},
    )
    async_db.add(uncataloged)
    await async_db.commit()

    catalog_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="3000-cataloged-series",
        metadata_json={"name": "Cataloged Series"},
    )
    async_db.add(catalog_identity)
    await async_db.flush()
    async_db.add(CatalogSeries(canonical_external_identity_id=catalog_identity.id))
    await async_db.commit()

    result = await search_catalog_series(async_db, provider="comicvine", limit=10)
    returned = {identity.external_id for identity in result}
    assert "3000-uncataloged-series" in returned
    assert "3000-cataloged-series" in returned


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
async def test_search_catalog_issues_includes_identities_without_catalog_row(
    async_db: AsyncSession,
):
    """Regression: #3220 acceptance criterion 3 keeps catalog-free issues searchable."""
    series = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="4000-series",
        metadata_json={"name": "Series"},
    )
    uncataloged = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="4000-issue-1",
        metadata_json={"name": "Issue 1"},
    )
    async_db.add_all([series, uncataloged])
    await async_db.commit()

    # The series gate passes on the pre-v1 contract even though neither row has
    # a catalog entry.
    result = await search_catalog_issues(
        async_db,
        series_external_id="4000-series",
        provider="comicvine",
        limit=10
    )
    assert [identity.external_id for identity in result] == ["4000-issue-1"]


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