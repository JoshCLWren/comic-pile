"""Pruned debug log routes stay absent (#4861).

The non-production debug router (``POST /api/debug/log`` plus its ``/api/v1``
alias) was deleted with its deferred mount. These guards assert both
aliases answer 404 regardless of environment flags and stay out of the
generated OpenAPI contract, while the retained eager health/ping/metrics
routes keep working.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/debug/log",
        "/api/v1/debug/log",
    ],
)
async def test_pruned_debug_log_returns_404(
    client: AsyncClient, path: str
) -> None:
    """The deleted debug log handlers answer 404 for anonymous callers."""
    response = await client.post(path, json={"level": "INFO", "message": "probe"})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_pruned_debug_log_returns_404_for_authenticated_user(
    auth_client: AsyncClient,
) -> None:
    """The deleted debug log handlers answer 404 for authenticated callers too."""
    response = await auth_client.post(
        "/api/debug/log", json={"level": "INFO", "message": "probe"}
    )
    assert response.status_code == 404


def test_pruned_debug_absent_from_openapi() -> None:
    """The pruned debug paths stay out of the generated OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/debug/log", "/api/v1/debug/log"):
        assert path not in schema["paths"], f"{path} must stay pruned"
