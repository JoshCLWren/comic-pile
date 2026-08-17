"""Tests for user preferences endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


class TestPreferences:
    """Test user preferences endpoints."""

    @pytest.mark.asyncio
    async def test_get_default_theme(self, auth_client: AsyncClient) -> None:
        """Authenticated user with no preferences gets classic theme."""
        response = await auth_client.get("/api/v1/users/me/preferences")
        assert response.status_code == 200
        data = response.json()
        assert data["theme"] == "classic"

    @pytest.mark.asyncio
    async def test_update_theme(self, auth_client: AsyncClient) -> None:
        """Authenticated user can update their theme."""
        response = await auth_client.patch(
            "/api/v1/users/me/preferences", json={"theme": "command-center"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["theme"] == "command-center"

    @pytest.mark.asyncio
    async def test_theme_persists_across_reads(self, auth_client: AsyncClient) -> None:
        """Updated theme persists on subsequent reads."""
        await auth_client.patch(
            "/api/v1/users/me/preferences", json={"theme": "ink-gold"}
        )
        response = await auth_client.get("/api/v1/users/me/preferences")
        assert response.status_code == 200
        assert response.json()["theme"] == "ink-gold"

    @pytest.mark.asyncio
    async def test_invalid_theme_rejected(self, auth_client: AsyncClient) -> None:
        """Invalid theme ID is rejected."""
        response = await auth_client.patch(
            "/api/v1/users/me/preferences", json={"theme": "nonexistent"}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unauthenticated_get_rejected(self, client: AsyncClient) -> None:
        """Unauthenticated GET is rejected."""
        response = await client.get("/api/v1/users/me/preferences")
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_unauthenticated_patch_rejected(self, client: AsyncClient) -> None:
        """Unauthenticated PATCH is rejected."""
        response = await client.patch(
            "/api/v1/users/me/preferences", json={"theme": "classic"}
        )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_all_themes_supported(
        self, auth_client: AsyncClient, async_db: AsyncSession
    ) -> None:
        """All three supported themes can be set and read."""
        for theme in ("classic", "ink-gold", "command-center"):
            response = await auth_client.patch(
                "/api/v1/users/me/preferences", json={"theme": theme}
            )
            assert response.status_code == 200
            assert response.json()["theme"] == theme

            read_response = await auth_client.get("/api/v1/users/me/preferences")
            assert read_response.status_code == 200
            assert read_response.json()["theme"] == theme
