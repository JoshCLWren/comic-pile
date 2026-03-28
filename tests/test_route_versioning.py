"""Tests for API route versioning aliases (issue #376).

Ensures /api/v1/sessions/* endpoints behave identically to /api/sessions/*.
"""

import pytest

from httpx import AsyncClient


@pytest.mark.asyncio
async def test_api_v1_alias_session_endpoint_matches_legacy(auth_client: AsyncClient) -> None:
    """Verify /api/v1/sessions/current/ mirrors /api/sessions/current/.

    This ensures that aliasing does not change behavior and both routes
    return identical responses when authenticated.
    """
    # Access both endpoints
    resp_v1 = await auth_client.get("/api/v1/sessions/current/")
    resp_legacy = await auth_client.get("/api/sessions/current/")

    # Status codes should match
    assert resp_v1.status_code == resp_legacy.status_code

    # If both are OK, compare response bodies for equality
    if resp_legacy.status_code == 200:
        assert resp_v1.json() == resp_legacy.json()
    else:
        # For non-200, ensure body presence matches (structure may differ per error)
        assert resp_v1.text == resp_legacy.text
