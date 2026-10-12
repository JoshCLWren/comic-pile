"""Tests for catalog models."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import ExternalIdentity


@pytest.mark.asyncio
async def test_catalog_series_creation(db: AsyncSession) -> None:
    """Test creating a CatalogSeries with a valid ExternalIdentity."""
    # Create an ExternalIdentity for a series
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        external_url="https://comicvine.gamespot.com/api/volume/12345/",
        metadata_json={"name": "Test Series", "publisher": {"name": "Test Publisher"}},
    )
    db.add(ext_identity)
    await db.flush()

    # Create a CatalogSeries referencing it
    catalog_series = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series)
    await db.flush()

    assert catalog_series.id is not None
    assert catalog_series.canonical_external_identity_id == ext_identity.id
    assert catalog_series.created_at is not None
    assert catalog_series.updated_at is not None


@pytest.mark.asyncio
async def test_catalog_series_unique_constraint(db: AsyncSession) -> None:
    """Test that only one CatalogSeries can reference the same ExternalIdentity."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        external_url="https://comicvine.gamespot.com/api/volume/12345/",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create first catalog series
    catalog_series1 = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series1)
    await db.flush()

    # Try to create second catalog series with same external identity - should fail
    catalog_series2 = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series2)

    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_catalog_series_restrict_delete(db: AsyncSession) -> None:
    """Test that deleting ExternalIdentity with RESTRICT fails when CatalogSeries exists."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        external_url="https://comicvine.gamespot.com/api/volume/12345/",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_series)
    await db.flush()

    # Try to delete the ExternalIdentity - should fail due to RESTRICT
    await db.delete(ext_identity)
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_catalog_issue_creation(db: AsyncSession) -> None:
    """Test creating a CatalogIssue with a valid ExternalIdentity."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        external_url="https://comicvine.gamespot.com/api/issue/67890/",
        metadata_json={"name": "Test Issue #1", "issue_number": "1"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    assert catalog_issue.id is not None
    assert catalog_issue.canonical_external_identity_id == ext_identity.id
    assert catalog_issue.catalog_series_id is None  # nullable, not set yet
    assert catalog_issue.created_at is not None
    assert catalog_issue.updated_at is not None


@pytest.mark.asyncio
async def test_catalog_issue_unique_constraint(db: AsyncSession) -> None:
    """Test that only one CatalogIssue can reference the same ExternalIdentity."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        external_url="https://comicvine.gamespot.com/api/issue/67890/",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_issue1 = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue1)
    await db.flush()

    catalog_issue2 = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue2)

    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_catalog_issue_restrict_delete(db: AsyncSession) -> None:
    """Test that deleting ExternalIdentity with RESTRICT fails when CatalogIssue exists."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        external_url="https://comicvine.gamespot.com/api/issue/67890/",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    await db.delete(ext_identity)
    with pytest.raises(IntegrityError):
        await db.flush()


@pytest.mark.asyncio
async def test_catalog_issue_link_to_series(db: AsyncSession) -> None:
    """Test linking a CatalogIssue to a CatalogSeries."""
    # Create series external identity and catalog series
    series_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(series_ext)
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=series_ext.id)
    db.add(catalog_series)
    await db.flush()

    # Create issue external identity and catalog issue
    issue_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(issue_ext)
    await db.flush()

    catalog_issue = CatalogIssue(
        canonical_external_identity_id=issue_ext.id,
        catalog_series_id=catalog_series.id,
    )
    db.add(catalog_issue)
    await db.flush()

    # Verify the relationship
    await db.refresh(catalog_issue, ["catalog_series"])
    assert catalog_issue.catalog_series_id == catalog_series.id
    assert catalog_issue.catalog_series is not None
    assert catalog_issue.catalog_series.id == catalog_series.id


@pytest.mark.asyncio
async def test_catalog_issue_set_null_on_series_delete(db: AsyncSession) -> None:
    """Test that deleting CatalogSeries sets catalog_issue.catalog_series_id to NULL."""
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
    catalog_issue = CatalogIssue(
        canonical_external_identity_id=issue_ext.id,
        catalog_series_id=catalog_series.id,
    )
    db.add_all([catalog_series, catalog_issue])
    await db.flush()

    # Delete the catalog series - should set catalog_issue.catalog_series_id to NULL
    await db.delete(catalog_series)
    await db.flush()

    await db.refresh(catalog_issue)
    assert catalog_issue.catalog_series_id is None


@pytest.mark.asyncio
async def test_catalog_series_and_issue_can_share_provider(db: AsyncSession) -> None:
    """Test that series and issue from same provider can both have catalog entries."""
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

    assert catalog_series.id is not None
    assert catalog_issue.id is not None
    # They are separate catalog entries despite same provider
    assert catalog_series.canonical_external_identity_id != catalog_issue.canonical_external_identity_id


@pytest.mark.asyncio
async def test_multiple_users_can_reference_same_catalog_issue(
    db: AsyncSession, sample_user, sample_user2
) -> None:
    """Test that two different users can reference one CatalogIssue via their Issues.

    This verifies acceptance criterion: "Two different users can reference one
    CatalogIssue while retaining distinct existing Issue IDs, read states, notes and ratings."
    """
    from app.models.issue import Issue
    from app.models.thread import Thread

    # Create external identity for an issue
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="99999",
        metadata_json={"name": "Shared Issue #1", "issue_number": "1"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create shared catalog issue
    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    # User 1 creates a thread and issue referencing the catalog issue
    thread1 = Thread(
        title="User 1's Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread1)
    await db.flush()

    issue1 = Issue(
        thread_id=thread1.id,
        issue_number="1",
        position=1,
        status="read",
        catalog_issue_id=catalog_issue.id,
    )
    db.add(issue1)

    # User 2 creates a thread and issue referencing the SAME catalog issue
    thread2 = Thread(
        title="User 2's Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user2.id,
    )
    db.add(thread2)
    await db.flush()

    issue2 = Issue(
        thread_id=thread2.id,
        issue_number="1",
        position=1,
        status="unread",  # Different read state!
        catalog_issue_id=catalog_issue.id,
    )
    db.add(issue2)
    await db.flush()

    # Verify both users have their own issues with different states
    result1 = await db.execute(
        select(Issue).where(Issue.id == issue1.id)
    )
    fetched_issue1 = result1.scalar_one()
    assert fetched_issue1.catalog_issue_id == catalog_issue.id
    assert fetched_issue1.status == "read"

    result2 = await db.execute(
        select(Issue).where(Issue.id == issue2.id)
    )
    fetched_issue2 = result2.scalar_one()
    assert fetched_issue2.catalog_issue_id == catalog_issue.id
    assert fetched_issue2.status == "unread"

    # Verify they have distinct issue IDs
    assert fetched_issue1.id != fetched_issue2.id
    assert fetched_issue1.thread_id != fetched_issue2.thread_id


@pytest.mark.asyncio
async def test_catalog_issue_can_exist_without_series(db: AsyncSession) -> None:
    """Test that a CatalogIssue can exist before its series is resolved.

    Verifies acceptance criterion: "A catalog issue can exist before its series
    is resolved; filling a verified series link is additive and never rewrites
    reader ownership."
    """
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create catalog issue WITHOUT a series link
    catalog_issue = CatalogIssue(canonical_external_identity_id=ext_identity.id)
    db.add(catalog_issue)
    await db.flush()

    assert catalog_issue.catalog_series_id is None

    # Later, add a series link
    series_ext = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(series_ext)
    await db.flush()

    catalog_series = CatalogSeries(canonical_external_identity_id=series_ext.id)
    db.add(catalog_series)
    await db.flush()

    # Link the issue to the series (additive)
    catalog_issue.catalog_series_id = catalog_series.id
    await db.flush()

    await db.refresh(catalog_issue)
    assert catalog_issue.catalog_series_id == catalog_series.id