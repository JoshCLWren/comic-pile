"""Tests for catalog repository functions."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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