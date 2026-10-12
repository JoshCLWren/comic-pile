"""Tests for catalog service functions."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogIssue, CatalogSeries
from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from app.models.thread import Thread
from app.services.catalog import (
    ensure_catalog_issue,
    ensure_catalog_series,
    get_catalog_issue_for_issue,
    get_catalog_series_for_thread,
    link_catalog_issue_to_series,
    set_issue_catalog_issue,
    set_thread_catalog_series,
)


@pytest.mark.asyncio
async def test_ensure_catalog_series_requires_confirmed_mapping(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_series requires a confirmed thread-series mapping."""
    # Create external identity for a series
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    # No confirmed mapping exists - should fail
    with pytest.raises(ValueError, match="has no confirmed series mapping"):
        await ensure_catalog_series(db, external_identity_id=ext_identity.id)


@pytest.mark.asyncio
async def test_ensure_catalog_series_succeeds_with_confirmed_mapping(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_series succeeds with a confirmed mapping."""
    from app.external_identities import link_thread_external_series

    # Create external identity for a series
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create a thread and confirm the series mapping
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    await link_thread_external_series(
        db,
        user_id=sample_user.id,
        thread_id=thread.id,
        external_identity_id=ext_identity.id,
        status="confirmed",
    )
    await db.flush()

    # Now ensure_catalog_series should succeed
    catalog_series = await ensure_catalog_series(db, external_identity_id=ext_identity.id)
    assert catalog_series is not None
    assert catalog_series.canonical_external_identity_id == ext_identity.id


@pytest.mark.asyncio
async def test_ensure_catalog_series_rejects_non_series(db: AsyncSession) -> None:
    """Test that ensure_catalog_series rejects non-series external identities."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",  # Not a series!
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    with pytest.raises(ValueError, match="is not a series"):
        await ensure_catalog_series(db, external_identity_id=ext_identity.id)


@pytest.mark.asyncio
async def test_ensure_catalog_issue_requires_confirmed_mapping(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_issue requires a confirmed issue-external-identity mapping."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    # No confirmed mapping exists - should fail
    with pytest.raises(ValueError, match="has no confirmed issue mapping"):
        await ensure_catalog_issue(db, external_identity_id=ext_identity.id)


@pytest.mark.asyncio
async def test_ensure_catalog_issue_succeeds_with_confirmed_mapping(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_issue succeeds with a confirmed mapping."""
    from app.external_identities import link_issue_external_identity

    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create a thread and issue
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    # Confirm the issue mapping
    await link_issue_external_identity(
        db,
        user_id=sample_user.id,
        issue_id=issue.id,
        external_identity_id=ext_identity.id,
        status="confirmed",
    )
    await db.flush()

    # Now ensure_catalog_issue should succeed
    catalog_issue = await ensure_catalog_issue(db, external_identity_id=ext_identity.id)
    assert catalog_issue is not None
    assert catalog_issue.canonical_external_identity_id == ext_identity.id


@pytest.mark.asyncio
async def test_ensure_catalog_issue_rejects_non_issue(db: AsyncSession) -> None:
    """Test that ensure_catalog_issue rejects non-issue external identities."""
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",  # Not an issue!
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    with pytest.raises(ValueError, match="is not an issue"):
        await ensure_catalog_issue(db, external_identity_id=ext_identity.id)


@pytest.mark.asyncio
async def test_ensure_catalog_series_idempotent(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_series is idempotent."""
    from app.external_identities import link_thread_external_series

    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="series",
        external_id="12345",
        metadata_json={"name": "Test Series"},
    )
    db.add(ext_identity)
    await db.flush()

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    await link_thread_external_series(
        db,
        user_id=sample_user.id,
        thread_id=thread.id,
        external_identity_id=ext_identity.id,
        status="confirmed",
    )
    await db.flush()

    # Multiple calls should return the same catalog series
    result1 = await ensure_catalog_series(db, external_identity_id=ext_identity.id)
    result2 = await ensure_catalog_series(db, external_identity_id=ext_identity.id)
    result3 = await ensure_catalog_series(db, external_identity_id=ext_identity.id)

    assert result1.id == result2.id == result3.id


@pytest.mark.asyncio
async def test_ensure_catalog_issue_idempotent(db: AsyncSession, sample_user) -> None:
    """Test that ensure_catalog_issue is idempotent."""
    from app.external_identities import link_issue_external_identity

    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="67890",
        metadata_json={"name": "Test Issue #1"},
    )
    db.add(ext_identity)
    await db.flush()

    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    await link_issue_external_identity(
        db,
        user_id=sample_user.id,
        issue_id=issue.id,
        external_identity_id=ext_identity.id,
        status="confirmed",
    )
    await db.flush()

    result1 = await ensure_catalog_issue(db, external_identity_id=ext_identity.id)
    result2 = await ensure_catalog_issue(db, external_identity_id=ext_identity.id)

    assert result1.id == result2.id


@pytest.mark.asyncio
async def test_link_catalog_issue_to_series_validates_existence(db: AsyncSession) -> None:
    """Test that link_catalog_issue_to_series validates both entries exist."""
    # Valid case
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

    # Should succeed
    result = await link_catalog_issue_to_series(
        db, catalog_issue_id=catalog_issue.id, catalog_series_id=catalog_series.id
    )
    assert result is not None

    # Invalid catalog_issue_id
    with pytest.raises(ValueError, match="CatalogIssue 99999 not found"):
        await link_catalog_issue_to_series(
            db, catalog_issue_id=99999, catalog_series_id=catalog_series.id
        )

    # Invalid catalog_series_id
    with pytest.raises(ValueError, match="CatalogSeries 88888 not found"):
        await link_catalog_issue_to_series(
            db, catalog_issue_id=catalog_issue.id, catalog_series_id=88888
        )


@pytest.mark.asyncio
async def test_get_catalog_series_for_thread(db: AsyncSession, sample_user) -> None:
    """Test getting catalog series for a thread."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    # No link yet
    result = await get_catalog_series_for_thread(db, thread.id)
    assert result is None

    # Create series and link
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

    thread.catalog_series_id = catalog_series.id
    await db.flush()

    result = await get_catalog_series_for_thread(db, thread.id)
    assert result is not None
    assert result.id == catalog_series.id


@pytest.mark.asyncio
async def test_get_catalog_issue_for_issue(db: AsyncSession, sample_user) -> None:
    """Test getting catalog issue for a reader issue."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    # No link yet
    result = await get_catalog_issue_for_issue(db, issue.id)
    assert result is None

    # Create catalog issue and link
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

    issue.catalog_issue_id = catalog_issue.id
    await db.flush()

    result = await get_catalog_issue_for_issue(db, issue.id)
    assert result is not None
    assert result.id == catalog_issue.id


@pytest.mark.asyncio
async def test_set_thread_catalog_series(db: AsyncSession, sample_user) -> None:
    """Test setting catalog series for a thread."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

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

    result = await set_thread_catalog_series(db, thread_id=thread.id, catalog_series_id=catalog_series.id)
    assert result is True

    await db.refresh(thread)
    assert thread.catalog_series_id == catalog_series.id

    # Nonexistent thread
    result = await set_thread_catalog_series(db, thread_id=99999, catalog_series_id=catalog_series.id)
    assert result is False


@pytest.mark.asyncio
async def test_set_issue_catalog_issue(db: AsyncSession, sample_user) -> None:
    """Test setting catalog issue for a reader issue."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

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

    result = await set_issue_catalog_issue(db, issue_id=issue.id, catalog_issue_id=catalog_issue.id)
    assert result is True

    await db.refresh(issue)
    assert issue.catalog_issue_id == catalog_issue.id

    # Nonexistent issue
    result = await set_issue_catalog_issue(db, issue_id=99999, catalog_issue_id=catalog_issue.id)
    assert result is False


@pytest.mark.asyncio
async def test_set_thread_catalog_series_validates_catalog_exists(db: AsyncSession, sample_user) -> None:
    """Test that set_thread_catalog_series validates catalog series exists."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    with pytest.raises(ValueError, match="CatalogSeries 99999 not found"):
        await set_thread_catalog_series(db, thread_id=thread.id, catalog_series_id=99999)


@pytest.mark.asyncio
async def test_set_issue_catalog_issue_validates_catalog_exists(db: AsyncSession, sample_user) -> None:
    """Test that set_issue_catalog_issue validates catalog issue exists."""
    thread = Thread(
        title="Test Thread",
        format="Comic",
        issues_remaining=0,
        queue_position=1,
        user_id=sample_user.id,
    )
    db.add(thread)
    await db.flush()

    issue = Issue(
        thread_id=thread.id,
        issue_number="1",
        position=1,
        status="unread",
    )
    db.add(issue)
    await db.flush()

    with pytest.raises(ValueError, match="CatalogIssue 99999 not found"):
        await set_issue_catalog_issue(db, issue_id=issue.id, catalog_issue_id=99999)


@pytest.mark.asyncio
async def test_independent_reader_state_preserved(db: AsyncSession, sample_user, sample_user2) -> None:
    """Test that two users referencing the same catalog issue retain independent state.

    Verifies acceptance criterion: "Two different users can reference one CatalogIssue
    while retaining distinct existing Issue IDs, read states, notes and ratings."
    """
    from app.external_identities import link_issue_external_identity

    # Create shared external identity and catalog issue
    ext_identity = ExternalIdentity(
        provider="comicvine",
        entity_type="issue",
        external_id="shared-issue-1",
        metadata_json={"name": "Shared Issue #1", "issue_number": "1"},
    )
    db.add(ext_identity)
    await db.flush()

    # Create confirmed mapping for user 1
    thread1 = Thread(
        title="User 1 Thread",
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
    )
    db.add(issue1)
    await db.flush()

    await link_issue_external_identity(
        db, user_id=sample_user.id, issue_id=issue1.id, external_identity_id=ext_identity.id, status="confirmed"
    )

    # Create confirmed mapping for user 2
    thread2 = Thread(
        title="User 2 Thread",
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
        status="unread",
    )
    db.add(issue2)
    await db.flush()

    await link_issue_external_identity(
        db, user_id=sample_user2.id, issue_id=issue2.id, external_identity_id=ext_identity.id, status="confirmed"
    )
    await db.flush()

    # Now create the shared catalog issue
    catalog_issue = await ensure_catalog_issue(db, external_identity_id=ext_identity.id)
    assert catalog_issue is not None

    # Link both reader issues to the same catalog issue
    await set_issue_catalog_issue(db, issue_id=issue1.id, catalog_issue_id=catalog_issue.id)
    await set_issue_catalog_issue(db, issue_id=issue2.id, catalog_issue_id=catalog_issue.id)
    await db.flush()

    # Verify both reader issues reference the same catalog issue
    await db.refresh(issue1)
    await db.refresh(issue2)
    assert issue1.catalog_issue_id == catalog_issue.id
    assert issue2.catalog_issue_id == catalog_issue.id

    # But they have different states
    assert issue1.status == "read"
    assert issue2.status == "unread"

    # And different IDs
    assert issue1.id != issue2.id
    assert issue1.thread_id != issue2.thread_id