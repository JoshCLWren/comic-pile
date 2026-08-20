"""Simple tests for the release ledger functionality."""

import pytest
from datetime import datetime, UTC
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_release_ledger_basic_workflow():
    """Test the basic workflow of creating and retrieving a release."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # Create a release (this is what implementation workers would do)
        payload = {
            "source_repository": "JoshCLWren/comic-pile",
            "source_pr_number": 1066,
            "source_merge_sha": "a" * 40,
            "merged_at": datetime.now(UTC).isoformat(),
            "released_at": datetime.now(UTC).isoformat(),
            "category": "What's New",
            "title": "Release 1066",
            "summary": "A user-facing release summary",
            "body": "Release body content",
            "visibility": "public",
            "status": "published",
            "sort_order": 0,
            "provenance_json": {"source": "github", "issue": 1066}
        }
        
        # Send the request
        response = await client.put("/api/v1/releases/", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        # Verify the response contains expected data
        data = response.json()
        assert "id" in data
        assert release_id := data["id"]
        assert release_id > 0
        assert data["title"] == "Release 1066"
        assert data["status"] == "published"
        assert data["visibility"] == "public"
        
        # Verify we can fetch the release
        get_response = await client.get(f"/api/v1/releases/{release_id}")
        assert get_response.status_code == 200
        data = get_response.json()
        assert data["id"] == release_id
        assert data["title"] == "Release 1066"
        assert data["status"] == "published"
        
        print("✅ Release ledger basic workflow test passed")


@pytest.mark.asyncio
async def test_release_ledger_idempotency():
    """Test that the same PR can be published multiple times."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # First publish
        payload = {
            "source_repository": "JoshCLWren/comic-pile",
            "source_pr_number": 1066,
            "source_merge_sha": "a" * 40,
            "merged_at": datetime.now(UTC).isoformat(),
            "released_at": datetime.now(UTC).isoformat(),
            "category": "What's New",
            "title": "Release 1066",
            "summary": "Initial summary",
            "body": "Initial body",
            "visibility": "public",
            "status": "published",
            "sort_order": 0,
            "provenance_json": {"source": "github"}
        }
        
        headers = {"X-Release-Writer-Token": "test-token-12345"}
        response1 = await client.put("/api/v1/releases/", json=payload, headers=headers)
        assert response.status_code == 200
        
        # Get the release ID
        release_id = response.json()["id"]
        
        # Make a small change and republish
        payload_updated = payload.copy()
        payload2 = payload2 = payload.copy()
        payload2["summary"] = "Updated summary"
        payload2["title"] = "Updated Release"
        
        response2 = await client.put("/api/v1/releases/", json=payload2, headers=headers)
        assert response2.status_code == 200
        
        # Verify it's the same release (idempotent)
        assert response2.status_code == 200
        assert response2.json()["id"] == release_id
        assert release2.json()["summary"] == "Updated summary"
        assert release2.json()["title"] == "Updated Release"
        
        print("✅ Release ledger idempotency test passed")


# Add a simple test to verify the API is working
@pytest.mark.asyncio
async def test_release_ledger_basic():
    """Simple test to verify the release ledger endpoint works."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        payload = {
            "source_repository": "JoshCLWren/comic-pile",
            "source_pr_number": 1066,
            "source_merge_sha": "b" * 40,
            "merged_at": datetime.now(UTC).isoformat(),
            "released_at": datetime.now(UTC).isoformat(),
            "category": "What's New",
            "title": "Test Release",
            "summary": "Test summary",
            "body": "Release body",
            "visibility": "public",
            "status": "published",
            "sort_order": 0,
            "provenance_json": {"source": "github"}
        }
        
        response = await client.put("/api/v1/releases/", json=payload)
        assert response.status_code == 200
        assert "id" in response.json()
        print("✅ Release ledger basic test passed")
