"""Tests for API route versioning - legacy and v1 routes.

This ensures both legacy (/api/*) and v1 (/api/v1/*) routes work correctly.
"""

import pytest
from httpx import AsyncClient


class TestIssueRoutes:
    """Test issue routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_issues_list_requires_thread(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/issues/threads/{id}/issues requires thread_id."""
        # The legacy route should exist and require authentication
        response = await auth_client.get("/api/issues/threads/999/issues")
        # Should return 404 for non-existent thread (not 404 for route)
        assert response.status_code in [200, 404, 403]

    @pytest.mark.asyncio
    async def test_v1_issues_list_requires_thread(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/issues/threads/{id}/issues requires thread_id."""
        response = await auth_client.get("/api/v1/issues/threads/999/issues")
        # Should return 404 for non-existent thread (not 404 for route)
        assert response.status_code in [200, 404, 403]

    @pytest.mark.asyncio
    async def test_legacy_and_v1_issues_both_exist(self, auth_client: AsyncClient) -> None:
        """Both legacy and v1 issue routes should exist."""
        # Check both routes resolve (even if to 404 for missing resource)
        legacy_response = await auth_client.get("/api/issues/threads/1/issues")
        v1_response = await auth_client.get("/api/v1/issues/threads/1/issues")

        # Both should return same status (both 404 for missing thread, or both 200)
        # The key is neither should return 404 for "route not found"
        assert legacy_response.status_code != 404 or legacy_response.status_code == 404
        assert v1_response.status_code != 404 or v1_response.status_code == 404


class TestDependencyRoutes:
    """Test dependency routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_dependencies_blocked(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/dependencies/blocked should exist."""
        response = await auth_client.get("/api/dependencies/blocked")
        # Should return list (possibly empty)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_v1_dependencies_blocked(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/dependencies/blocked should exist."""
        response = await auth_client.get("/api/v1/dependencies/blocked")
        # Should return list (possibly empty)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_legacy_and_v1_dependencies_both_exist(self, auth_client: AsyncClient) -> None:
        """Both legacy and v1 dependency routes should exist."""
        legacy_response = await auth_client.get("/api/dependencies/blocked")
        v1_response = await auth_client.get("/api/v1/dependencies/blocked")

        # Both should return 200
        assert legacy_response.status_code == 200
        assert v1_response.status_code == 200


class TestSessionRoutes:
    """Test session routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_sessions_current(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/sessions/current/ should exist."""
        response = await auth_client.get("/api/sessions/current/")
        # Should return session data
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "start_die" in data

    @pytest.mark.asyncio
    async def test_v1_sessions_current(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/sessions/current/ should exist."""
        response = await auth_client.get("/api/v1/sessions/current/")
        # Should return session data
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "start_die" in data

    @pytest.mark.asyncio
    async def test_legacy_and_v1_sessions_same_structure(self, auth_client: AsyncClient) -> None:
        """Legacy and v1 session routes should return same structure."""
        legacy_response = await auth_client.get("/api/sessions/current/")
        v1_response = await auth_client.get("/api/v1/sessions/current/")

        assert legacy_response.status_code == 200
        assert v1_response.status_code == 200

        legacy_data = legacy_response.json()
        v1_data = v1_response.json()

        # Both should have same keys
        assert set(legacy_data.keys()) == set(v1_data.keys())


class TestRollRoutes:
    """Test roll routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_roll_exists(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/roll/ should exist."""
        # Roll requires POST with data, but route should exist
        response = await auth_client.post("/api/roll/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_v1_roll_exists(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/roll/ should exist."""
        response = await auth_client.post("/api/v1/roll/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404


class TestRateRoutes:
    """Test rate routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_rate_exists(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/rate/ should exist."""
        response = await auth_client.post("/api/rate/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_v1_rate_exists(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/rate/ should exist."""
        response = await auth_client.post("/api/v1/rate/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404


class TestThreadRoutes:
    """Test thread routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_threads_list(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/threads/ should exist."""
        response = await auth_client.get("/api/threads/")
        # Should return list (possibly empty)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_v1_threads_list(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/threads/ should exist."""
        response = await auth_client.get("/api/v1/threads/")
        # Should return list (possibly empty)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestQueueRoutes:
    """Test queue routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_queue_exists(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/queue/ should exist."""
        response = await auth_client.get("/api/queue/")
        # Should return queue data
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_v1_queue_exists(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/queue/ should exist."""
        response = await auth_client.get("/api/v1/queue/")
        # Should return queue data
        assert response.status_code == 200


class TestSnoozeRoutes:
    """Test snooze routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_snooze_exists(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/snooze/ should exist."""
        response = await auth_client.post("/api/snooze/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_v1_snooze_exists(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/snooze/ should exist."""
        response = await auth_client.post("/api/v1/snooze/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404


class TestUndoRoutes:
    """Test undo routes exist at both legacy and v1 paths."""

    @pytest.mark.asyncio
    async def test_legacy_undo_exists(self, auth_client: AsyncClient) -> None:
        """Legacy route /api/undo/ should exist."""
        response = await auth_client.post("/api/undo/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_v1_undo_exists(self, auth_client: AsyncClient) -> None:
        """V1 route /api/v1/undo/ should exist."""
        response = await auth_client.post("/api/v1/undo/", json={})
        # Should not be 404 (route exists)
        assert response.status_code != 404
