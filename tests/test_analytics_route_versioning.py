"""Pruned Python analytics versioning aliases stay absent (#4861).

The Python ``/api/analytics/metrics`` and ``/api/v1/analytics/metrics``
handlers were deleted; the frontend uses the native Rust
``GET /api/v2/analytics/metrics`` resource (#4348). These guards assert both
aliases answer 404 instead of mirroring each other.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pruned_analytics_aliases_both_404(auth_client: AsyncClient) -> None:
    """Both the legacy and canonical Python analytics paths are gone."""
    canonical = await auth_client.get("/api/v1/analytics/metrics")
    legacy = await auth_client.get("/api/analytics/metrics")

    assert canonical.status_code == 404
    assert legacy.status_code == 404
