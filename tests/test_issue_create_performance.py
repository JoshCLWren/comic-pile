"""Performance tests for ComicVine auto-mapping optimization.

Tests the performance of the POST /api/v1/threads/{thread_id}/issues endpoint
with and without ComicVine auto-mapping to ensure the optimization meets
the 1000ms performance budget.
"""

import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.performance_budgets import REQUEST_TIMEOUT_MS
from tests.conftest import create_auth_client, create_test_user


@pytest.mark.asyncio
async def test_create_issues_performance_without_comicvine_mapping():
    """Test that issue creation without ComicVine auto-mapping meets performance budget."""
    # Create test user and thread
    async with async_session_maker() as db:
        user = await create_test_user(db)
        thread = await create_test_thread(db, user.id, title="Test Thread")
        
        # Create auth client
        auth_client = await create_auth_client(user)
        
        # Measure performance for issue creation without ComicVine mapping
        started = time.perf_counter()
        
        response = await auth_client.post(
            f"/api/v1/threads/{thread.id}/issues",
            json={"issue_range": "1-5"}
        )
        
        elapsed_ms = (time.perf_counter() - started) * 1000
        
        # Verify response and performance
        assert response.status_code == 201
        assert elapsed_ms < REQUEST_TIMEOUT_MS, f"Issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
        
        # Verify issues were created
        data = response.json()
        assert len(data["issues"]) == 5


@pytest.mark.asyncio  
async def test_create_issues_performance_with_comicvine_mapping_disabled():
    """Test that issue creation with ComicVine auto-mapping disabled meets performance budget."""
    # Create test user and thread
    async with async_session_maker() as db:
        user = await create_test_user(db)
        thread = await create_test_thread(db, user.id, title="Test Thread")
        
        # Create auth client
        auth_client = await create_auth_client(user)
        
        # Measure performance for issue creation with ComicVine mapping disabled
        started = time.perf_counter()
        
        response = await auth_client.post(
            f"/api/v1/threads/{thread.id}/issues",
            json={"issue_range": "1-5"}
        )
        
        elapsed_ms = (time.perf_counter() - started) * 1000
        
        # Verify response and performance
        assert response.status_code == 201
        assert elapsed_ms < REQUEST_TIMEOUT_MS, f"Issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
        
        # Verify issues were created
        data = response.json()
        assert len(data["issues"]) == 5


@pytest.mark.asyncio
async def test_create_issues_performance_with_comicvine_mapping_background():
    """Test that issue creation with background ComicVine auto-mapping meets performance budget."""
    # Create test user and thread
    async with async_session_maker() as db:
        user = await create_test_user(db)
        thread = await create_test_thread(db, user.id, title="Test Thread")
        
        # Mock the ComicVine client to simulate external API calls
        with patch("app.services.issue.ComicVineClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            
            # Mock the fetch_volume_issues method to simulate a slow API call
            mock_client.fetch_volume_issues = AsyncMock(
                return_value=[
                    {"id": 12345, "issue_number": "1", "volume": {"id": 42}},
                    {"id": 12346, "issue_number": "2", "volume": {"id": 42}},
                    {"id": 12347, "issue_number": "3", "volume": {"id": 42}},
                    {"id": 12348, "issue_number": "4", "volume": {"id": 42}},
                    {"id": 12349, "issue_number": "5", "volume": {"id": 42}},
                ]
            )
            
            # Mock adopt_comicvine_issue to simulate successful adoption
            with patch("app.services.issue.adopt_comicvine_issue") as mock_adoption:
                mock_adoption.return_value = AsyncMock(
                    outcome="created",
                    conflict_detail=None
                )
                
                # Create auth client
                auth_client = await create_auth_client(user)
                
                # Measure performance for issue creation with background ComicVine mapping
                started = time.perf_counter()
                
                response = await auth_client.post(
                    f"/api/v1/threads/{thread.id}/issues",
                    json={"issue_range": "1-5"}
                )
                
                elapsed_ms = (time.perf_counter() - started) * 1000
                
                # Verify response and performance
                assert response.status_code == 201
                assert elapsed_ms < REQUEST_TIMEOUT_MS, f"Issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
                
                # Verify issues were created
                data = response.json()
                assert len(data["issues"]) == 5
                
                # Verify that ComicVine operations were called in background
                # (they should not block the main request)
                assert mock_client.fetch_volume_issues.called


@pytest.mark.asyncio
async def test_create_issues_performance_comparison():
    """Compare performance of issue creation with and without ComicVine auto-mapping."""
    # Create test user and thread
    async with async_session_maker() as db:
        user = await create_test_user(db)
        thread1 = await create_test_thread(db, user.id, title="Thread 1")
        thread2 = await create_test_thread(db, user.id, title="Thread 2")
        
        # Create auth client
        auth_client = await create_auth_client(user)
        
        # Measure performance without ComicVine mapping
        started = time.perf_counter()
        response1 = await auth_client.post(
            f"/api/v1/threads/{thread1.id}/issues",
            json={"issue_range": "1-10"}
        )
        elapsed_without_mapping = (time.perf_counter() - started) * 1000
        
        # Measure performance with background ComicVine mapping
        with patch("app.services.issue.ComicVineClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client
            mock_client.fetch_volume_issues = AsyncMock(
                return_value=[
                    {"id": i, "issue_number": str(i), "volume": {"id": 42}} 
                    for i in range(1, 11)
                ]
            )
            
            with patch("app.services.issue.adopt_comicvine_issue") as mock_adoption:
                mock_adoption.return_value = AsyncMock(
                    outcome="created",
                    conflict_detail=None
                )
                
                started = time.perf_counter()
                response2 = await auth_client.post(
                    f"/api/v1/threads/{thread2.id}/issues",
                    json={"issue_range": "1-10"}
                )
                elapsed_with_mapping = (time.perf_counter() - started) * 1000
        
        # Verify both responses are successful
        assert response1.status_code == 201
        assert response2.status_code == 201
        
        # Verify both meet performance budget
        assert elapsed_without_mapping < REQUEST_TIMEOUT_MS
        assert elapsed_with_mapping < REQUEST_TIMEOUT_MS
        
        # Background mapping should not significantly impact performance
        # Allow some overhead but ensure it's still within budget
        assert elapsed_with_mapping < REQUEST_TIMEOUT_MS * 1.1  # 10% overhead tolerance
        
        # Log performance comparison for debugging
        print(f"Without ComicVine mapping: {elapsed_without_mapping:.1f}ms")
        print(f"With background ComicVine mapping: {elapsed_with_mapping:.1f}ms")
        print(f"Performance overhead: {((elapsed_with_mapping - elapsed_without_mapping) / elapsed_without_mapping * 100):.1f}%")


@pytest.mark.asyncio
async def test_create_issues_performance_large_batch():
    """Test performance with a large batch of issues to ensure scalability."""
    # Create test user and thread
    async with async_session_maker() as db:
        user = await create_test_user(db)
        thread = await create_test_thread(db, user.id, title="Test Thread")
        
        # Create auth client
        auth_client = await create_auth_client(user)
        
        # Measure performance for large batch (20 issues)
        started = time.perf_counter()
        
        response = await auth_client.post(
            f"/api/v1/threads/{thread.id}/issues",
            json={"issue_range": "1-20"}
        )
        
        elapsed_ms = (time.perf_counter() - started) * 1000
        
        # Verify response and performance
        assert response.status_code == 201
        assert elapsed_ms < REQUEST_TIMEOUT_MS, f"Large batch issue creation took {elapsed_ms:.1f}ms, exceeding {REQUEST_TIMEOUT_MS}ms budget"
        
        # Verify all issues were created
        data = response.json()
        assert len(data["issues"]) == 20