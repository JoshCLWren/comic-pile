"""Tests for reading plan sync API endpoints."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.user import User
from app.auth import get_current_user
from app.database import get_db


@pytest.fixture
def mock_user():
    """Mock current user."""
    user = User(
        id=1,
        email="test@example.com",
        username="testuser",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return user


@pytest.fixture
def mock_db():
    """Mock database session."""
    return AsyncMock()


@pytest.fixture
def client(mock_user, mock_db):
    """Test client with authenticated user."""
    app = create_app(serve_frontend=False)

    # Override the dependencies
    async def override_get_current_user():
        return mock_user

    async def override_get_db():
        return mock_db

    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app)


@pytest.fixture
def mock_sync_service():
    """Mock the sync service."""
    with patch("app.api.reading_plan_sync.sync_released_issues") as mock:
        yield mock


@pytest.fixture
def sample_sync_result():
    """Sample sync result for testing."""
    return {
        "total_sources": 3,
        "enabled_sources": 2,
        "successful_sources": 1,
        "failed_sources": 0,
        "created_issues": 3,
        "reused_issues": 1,
        "future_skips": 0,
        "unknown_date_skips": 1,
        "conflicts": 0,
        "errors": [],
    }


def test_sync_released_issues_endpoint_success(client, mock_user, mock_db, mock_sync_service, sample_sync_result):
    """Test successful sync endpoint."""
    # Setup mocks
    mock_sync_service.return_value = type(
        "MockSyncResult", (), sample_sync_result
    )()

    # Make request
    response = client.post(
        "/api/sync",
        json={
            "as_of": "2023-04-01T00:00:00Z",
            "refresh": True,
        }
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["result"] == sample_sync_result
    assert "created 3 issues" in data["message"]
    assert "reused 1 issues" in data["message"]

    # Verify service was called correctly
    mock_sync_service.assert_called_once()
    call_args = mock_sync_service.call_args
    assert call_args.kwargs["as_of"] == datetime(2023, 4, 1, tzinfo=timezone.utc)
    assert call_args.kwargs["refresh"] is True
    assert call_args.kwargs["db"] == mock_db


def test_sync_released_issues_endpoint_with_partial_failure(
    client, mock_user, mock_db, mock_sync_service
):
    """Test sync endpoint with partial failures."""
    # Setup mocks for partial failure
    partial_result = {
        "total_sources": 3,
        "enabled_sources": 2,
        "successful_sources": 1,
        "failed_sources": 1,
        "created_issues": 2,
        "reused_issues": 1,
        "future_skips": 0,
        "unknown_date_skips": 0,
        "conflicts": 0,
        "errors": [
            {
                "source_id": 3,
                "plan_id": 2,
                "thread_id": 2,
                "volume_id": 2002,
                "error": "Volume sync failed: API error",
            }
        ],
    }

    mock_sync_service.return_value = type("MockSyncResult", (), partial_result)()

    # Make request
    response = client.post(
        "/api/sync",
        json={
            "as_of": "2023-04-01T00:00:00Z",
            "refresh": False,
        }
    )

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False  # Should be False when there are failures
    assert data["result"] == partial_result
    assert "1 failed" in data["message"]

    # Verify service was called correctly
    mock_sync_service.assert_called_once()
    call_args = mock_sync_service.call_args
    assert call_args.kwargs["refresh"] is False


def test_sync_released_issues_endpoint_invalid_date(client, mock_user, mock_db, mock_sync_service):
    """Test sync endpoint with invalid date format."""
    # Make request with invalid date
    response = client.post(
        "/api/sync",
        json={
            "as_of": "invalid-date-format",
            "refresh": True,
        }
    )

    # Verify response
    assert response.status_code == 422  # Validation error
    data = response.json()
    assert "date" in data["detail"][0]["msg"].lower()


def test_sync_released_issues_endpoint_exception(client, mock_user, mock_db, mock_sync_service):
    """Test sync endpoint with service exception."""
    # Setup mocks for service exception
    mock_sync_service.side_effect = Exception("Database connection failed")

    # Make request
    response = client.post(
        "/api/sync",
        json={
            "as_of": "2023-04-01T00:00:00Z",
            "refresh": True,
        }
    )

    # Verify response
    assert response.status_code == 500
    data = response.json()
    assert "Sync failed" in data["detail"]


def test_get_sync_status_endpoint_success(client, mock_user, mock_db):
    """Test sync status endpoint success."""
    # Setup mocks
    from app.models.reading_plan_release_source import ReadingPlanReleaseSource
    from app.models.continuity_plan import ContinuityPlan
    from app.models.thread import Thread
    from app.models.external_identity import ExternalIdentity

    plan = ContinuityPlan(
        id=1,
        user_id=1,
        name="Test Plan",
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

    external_identity = ExternalIdentity(
        id=1,
        provider="comicvine",
        entity_type="series",
        external_id="2001",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    source1 = ReadingPlanReleaseSource(
        id=1,
        plan_id=1,
        thread_id=1,
        external_identity_id=1,
        enabled=True,
        last_synced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    # Set relationships manually for test
    source1.reading_plan = plan
    source1.thread = thread
    source1.external_identity = external_identity

    source2 = ReadingPlanReleaseSource(
        id=2,
        plan_id=1,
        thread_id=1,
        external_identity_id=2,
        enabled=False,
        last_synced_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    external_identity2 = ExternalIdentity(
        id=2,
        provider="comicvine",
        entity_type="series",
        external_id="2002",
        confirmed=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    source2.reading_plan = plan
    source2.thread = thread
    source2.external_identity = external_identity2

    with patch("app.api.reading_plan_sync.get_enabled_sources_by_user") as mock_get_sources:
        mock_get_sources.return_value = [source1, source2]

        # Make request
        response = client.get("/api/status")

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert data["total_enabled_sources"] == 2
    assert len(data["sources"]) == 2

    # Verify first source
    source1_data = data["sources"][0]
    assert source1_data["id"] == 1
    assert source1_data["reading_plan_id"] == 1
    assert source1_data["thread_id"] == 1
    assert source1_data["volume_id"] == 2001
    assert source1_data["enabled"] is True
    assert source1_data["last_synced_at"] is not None

    # Verify second source
    source2_data = data["sources"][1]
    assert source2_data["id"] == 2
    assert source2_data["enabled"] is False
    assert source2_data["last_synced_at"] is None


def test_get_sync_status_endpoint_exception(client, mock_user, mock_db):
    """Test sync status endpoint with repository exception."""
    # Setup mocks for repository exception
    with patch("app.api.reading_plan_sync.get_enabled_sources_by_user") as mock_get_sources:
        mock_get_sources.side_effect = Exception("Database error")

        # Make request
        response = client.get("/api/status")

    # Verify response
    assert response.status_code == 500
    data = response.json()
    assert "Failed to get sync status" in data["detail"]


def test_sync_endpoint_without_refresh(client, mock_user, mock_db, mock_sync_service, sample_sync_result):
    """Test sync endpoint with refresh=False."""
    # Setup mocks
    mock_sync_service.return_value = type(
        "MockSyncResult", (), sample_sync_result
    )()

    # Make request without refresh
    response = client.post(
        "/api/sync",
        json={
            "as_of": "2023-04-01T00:00:00Z",
            "refresh": False,
        }
    )

    # Verify response
    assert response.status_code == 200

    # Verify service was called with refresh=False
    mock_sync_service.assert_called_once()
    call_args = mock_sync_service.call_args
    assert call_args.kwargs["refresh"] is False


def test_sync_endpoint_default_refresh(client, mock_user, mock_db, mock_sync_service, sample_sync_result):
    """Test sync endpoint with default refresh=True."""
    # Setup mocks
    mock_sync_service.return_value = type(
        "MockSyncResult", (), sample_sync_result
    )()

    # Make request without refresh parameter (should default to True)
    response = client.post(
        "/api/sync",
        json={
            "as_of": "2023-04-01T00:00:00Z",
        }
    )

    # Verify response
    assert response.status_code == 200

    # Verify service was called with refresh=True (default)
    mock_sync_service.assert_called_once()
    call_args = mock_sync_service.call_args
    assert call_args.kwargs["refresh"] is True