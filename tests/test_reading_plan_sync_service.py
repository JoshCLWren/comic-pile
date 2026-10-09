"""Tests for reading plan sync service."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.reading_plan_release_source import ReadingPlanReleaseSource
from app.models.thread import Thread
from app.models.reading_plan import ReadingPlan
from app.models.external_identity import ExternalIdentity
from app.models.issue import Issue
from app.services.reading_plan_sync_service import (
    sync_released_issues,
    SyncResult,
    SourceSyncResult,
)
from app.comicvine_provider import ComicVineProvider


@pytest.fixture
def mock_db():
    """Mock database session."""
    return AsyncMock()


@pytest.fixture
def mock_comicvine_provider():
    """Mock ComicVine provider."""
    with patch("app.services.reading_plan_sync_service.ComicVineProvider") as mock:
        provider = AsyncMock()
        mock.return_value = provider
        yield provider


@pytest.fixture
def mock_adopt_comicvine_issue():
    """Mock the comicvine issue adoption service."""
    with patch("app.services.reading_plan_sync_service.adopt_comicvine_issue") as mock:
        yield mock


@pytest.fixture
def mock_release_source_repo():
    """Mock release source repository."""
    with patch("app.services.reading_plan_sync_service.reading_plan_release_source_repository") as mock:
        yield mock


@pytest.fixture
def mock_thread_repo():
    """Mock thread repository."""
    with patch("app.services.reading_plan_sync_service.thread_repository") as mock:
        yield mock


@pytest.fixture
def mock_external_identity_repo():
    """Mock external identity repository."""
    with patch("app.services.reading_plan_sync_service.external_identity_repository") as mock:
        yield mock


@pytest.fixture
def mock_issue_repo():
    """Mock issue repository."""
    with patch("app.services.reading_plan_sync_service.issue_repository") as mock:
        yield mock


@pytest.fixture
def sample_comicvine_issues():
    """Sample ComicVine issues for testing."""
    return [
        {
            "id": 1001,
            "issue_number": "1",
            "store_date": "2023-01-15T00:00:00Z",
            "cover_date": "2023-01-10T00:00:00Z",
            "title": "Issue 1",
        },
        {
            "id": 1002,
            "issue_number": "2",
            "store_date": "2023-02-20T00:00:00Z",
            "cover_date": "2023-02-15T00:00:00Z",
            "title": "Issue 2",
        },
        {
            "id": 1003,
            "issue_number": "3",
            "store_date": "2023-03-25T00:00:00Z",
            "cover_date": "2023-03-20T00:00:00Z",
            "title": "Issue 3",
        },
        {
            "id": 1004,
            "issue_number": "4",
            "store_date": None,  # Missing store_date
            "cover_date": "2023-04-20T00:00:00Z",
            "title": "Issue 4 (No Store Date)",
        },
        {
            "id": 1005,
            "issue_number": "5",
            "store_date": "2023-05-30T00:00:00Z",
            "cover_date": "2023-05-25T00:00:00Z",
            "title": "Issue 5",
        },
    ]


@pytest.fixture
def sample_release_sources():
    """Sample release sources for testing."""
    plan = ReadingPlan(
        id=1,
        user_id=1,
        title="Test Plan",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    thread = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    source1 = ReadingPlanReleaseSource(
        id=1,
        reading_plan_id=1,
        thread_id=1,
        volume_id=2001,
        enabled=True,
        last_synced_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        reading_plan=plan,
    )
    
    source2 = ReadingPlanReleaseSource(
        id=2,
        reading_plan_id=1,
        thread_id=1,
        volume_id=2001,  # Same volume as source1
        enabled=True,
        last_synced_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        reading_plan=plan,
    )
    
    source3 = ReadingPlanReleaseSource(
        id=3,
        reading_plan_id=2,
        thread_id=2,
        volume_id=2002,
        enabled=False,  # Disabled source
        last_synced_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        reading_plan=ReadingPlan(
            id=2,
            user_id=1,
            title="Another Plan",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    )
    
    return [source1, source2, source3]


@pytest.fixture
def sample_external_identities():
    """Sample external identities for testing."""
    return [
        ExternalIdentity(
            id=1,
            provider="comicvine",
            external_id="1001",
            confirmed=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
        ExternalIdentity(
            id=2,
            provider="comicvine",
            external_id="1002",
            confirmed=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ),
    ]


@pytest.mark.asyncio
async def test_sync_released_issues_basic(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    mock_issue_repo,
    sample_comicvine_issues,
    sample_release_sources,
    sample_external_identities,
):
    """Test basic sync functionality."""
    # Setup mocks
    mock_release_source_repo.get_enabled_sources.return_value = sample_release_sources
    mock_comicvine_provider.fetch_volume_issues.return_value = sample_comicvine_issues
    mock_external_identity_repo.get_by_provider_and_volume.return_value = sample_external_identities
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Mock adoption results
    mock_adopt_comicvine_issue.side_effect = [
        "created",  # Issue 1001 - created
        "reused",   # Issue 1002 - already exists
        "created",  # Issue 1003 - created
        "created",  # Issue 1005 - created (skips 1004 due to missing store_date)
    ]
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results
    assert isinstance(result, SyncResult)
    assert result.total_sources == 3
    assert result.enabled_sources == 2  # Only 2 sources are enabled
    assert result.successful_sources == 1  # 1 volume (2001) with 2 sources
    assert result.failed_sources == 0
    assert result.created_issues == 3  # Issues 1001, 1003, 1005 created
    assert result.reused_issues == 1  # Issue 1002 reused
    assert result.future_skips == 0
    assert result.unknown_date_skips == 1  # Issue 1004 skipped (no store_date)
    assert result.conflicts == 0
    assert len(result.errors) == 0
    
    # Verify ComicVine provider was called once for volume 2001
    mock_comicvine_provider.fetch_volume_issues.assert_called_once_with(2001, refresh=True)


@pytest.mark.asyncio
async def test_sync_released_issues_future_skips(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    sample_comicvine_issues,
    sample_release_sources,
    sample_external_identities,
):
    """Test that future issues are skipped."""
    # Setup mocks
    mock_release_source_repo.get_enabled_sources.return_value = [sample_release_sources[0]]
    mock_comicvine_provider.fetch_volume_issues.return_value = sample_comicvine_issues
    mock_external_identity_repo.get_by_provider_and_volume.return_value = []
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Mock adoption results - all should be skipped due to future dates
    mock_adopt_comicvine_issue.side_effect = [
        "future_skip",  # Issue 1001 - future (store_date > as_of)
        "future_skip",  # Issue 1002 - future
        "future_skip",  # Issue 1003 - future
        "future_skip",  # Issue 1005 - future
    ]
    
    # Set sync boundary date (before any issues)
    as_of = datetime(2022, 12, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 1
    assert result.failed_sources == 0
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 4  # All issues are future
    assert result.unknown_date_skips == 1  # Issue 1004 skipped (no store_date)
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_sync_released_issues_volume_failure_isolation(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    sample_release_sources,
):
    """Test that failure in one volume doesn't affect others."""
    # Setup mocks for volume failure
    mock_release_source_repo.get_enabled_sources.return_value = sample_release_sources
    mock_comicvine_provider.fetch_volume_issues.side_effect = Exception("ComicVine API error")
    
    # Execute sync
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 0
    assert result.failed_sources == 1  # Volume 2001 failed
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 0
    assert result.unknown_date_skips == 0
    assert result.conflicts == 0
    assert len(result.errors) == 1
    assert "ComicVine API error" in result.errors[0]["error"]


@pytest.mark.asyncio
async def test_sync_released_issues_duplicate_volume_deduplication(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    mock_issue_repo,
    sample_comicvine_issues,
    sample_release_sources,
    sample_external_identities,
):
    """Test that multiple sources for same volume don't cause duplicate fetching."""
    # Setup mocks
    mock_release_source_repo.get_enabled_sources.return_value = sample_release_sources[:2]  # 2 sources for same volume
    mock_comicvine_provider.fetch_volume_issues.return_value = sample_comicvine_issues
    mock_external_identity_repo.get_by_provider_and_volume.return_value = sample_external_identities
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Mock adoption results
    mock_adopt_comicvine_issue.side_effect = [
        "created",  # Issue 1001
        "reused",   # Issue 1002
        "created",  # Issue 1003
        "created",  # Issue 1005
    ]
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results - should only fetch volume once but process both sources
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 1  # Only 1 volume processed
    assert result.failed_sources == 0
    assert result.created_issues == 3  # Same as single volume test
    assert result.reused_issues == 1
    assert result.future_skips == 0
    assert result.unknown_date_skips == 1
    assert result.conflicts == 0
    
    # Verify ComicVine provider was called only once for volume 2001
    mock_comicvine_provider.fetch_volume_issues.assert_called_once_with(2001, refresh=True)


@pytest.mark.asyncio
async def test_sync_released_issues_conflict_handling(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    sample_release_sources,
    sample_external_identities,
):
    """Test that conflicts are handled properly."""
    # Setup mocks
    mock_release_source_repo.get_enabled_sources.return_value = [sample_release_sources[0]]
    mock_comicvine_provider.fetch_volume_issues.return_value = [
        {"id": 1001, "issue_number": "1", "store_date": "2023-01-15T00:00:00Z", "title": "Issue 1"}
    ]
    mock_external_identity_repo.get_by_provider_and_volume.return_value = sample_external_identities
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Mock adoption result - conflict
    mock_adopt_comicvine_issue.return_value = "conflict"
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 1
    assert result.failed_sources == 0
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 0
    assert result.unknown_date_skips == 0
    assert result.conflicts == 1
    assert len(result.errors) == 0


@pytest.mark.asyncio
async def test_sync_released_issues_invalid_store_date(
    mock_db,
    mock_comicvine_provider,
    mock_adopt_comicvine_issue,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    sample_release_sources,
    sample_external_identities,
):
    """Test handling of invalid store_date values."""
    # Setup mocks with invalid store_date
    mock_release_source_repo.get_enabled_sources.return_value = [sample_release_sources[0]]
    mock_comicvine_provider.fetch_volume_issues.return_value = [
        {
            "id": 1001,
            "issue_number": "1",
            "store_date": "invalid-date",  # Invalid date format
            "title": "Issue 1",
        }
    ]
    mock_external_identity_repo.get_by_provider_and_volume.return_value = []
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results - invalid store_date should be treated as unknown_date_skip
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 1
    assert result.failed_sources == 0
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 0
    assert result.unknown_date_skips == 1  # Invalid date treated as unknown
    assert result.conflicts == 0


@pytest.mark.asyncio
async def test_sync_released_issues_thread_user_mismatch(
    mock_db,
    mock_comicvine_provider,
    mock_release_source_repo,
    mock_thread_repo,
    sample_release_sources,
):
    """Test handling of thread/user mismatch."""
    # Setup mocks for thread user mismatch
    mock_release_source_repo.get_enabled_sources.return_value = [sample_release_sources[0]]
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=2,  # Different user than plan
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results - should fail due to user mismatch
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 0
    assert result.failed_sources == 1
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 0
    assert result.unknown_date_skips == 0
    assert result.conflicts == 0
    assert len(result.errors) == 1
    assert "user mismatch" in result.errors[0]["error"]


@pytest.mark.asyncio
async def test_sync_released_issues_unconfirmed_volume_mapping(
    mock_db,
    mock_comicvine_provider,
    mock_release_source_repo,
    mock_thread_repo,
    mock_external_identity_repo,
    sample_release_sources,
):
    """Test handling of unconfirmed volume mapping."""
    # Setup mocks for unconfirmed mapping
    mock_release_source_repo.get_enabled_sources.return_value = [sample_release_sources[0]]
    mock_thread_repo.get_by_id.return_value = Thread(
        id=1,
        user_id=1,
        title="Test Thread",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_external_identity_repo.get_by_provider_and_external_id.return_value = ExternalIdentity(
        id=1,
        provider="comicvine",
        external_id="2001",
        confirmed=False,  # Unconfirmed mapping
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Set sync boundary date
    as_of = datetime(2023, 4, 1, tzinfo=timezone.utc)
    
    # Execute sync
    result = await sync_released_issues(mock_db, as_of, refresh=True)
    
    # Verify results - should fail due to unconfirmed mapping
    assert result.total_sources == 3
    assert result.enabled_sources == 2
    assert result.successful_sources == 0
    assert result.failed_sources == 1
    assert result.created_issues == 0
    assert result.reused_issues == 0
    assert result.future_skips == 0
    assert result.unknown_date_skips == 0
    assert result.conflicts == 0
    assert len(result.errors) == 1
    assert "not confirmed" in result.errors[0]["error"]