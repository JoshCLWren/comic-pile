"""Pruned crossover-template routes stay absent (#4861).

The external crossover template preview/adopt handlers
(``POST /api/v1/crossover-templates/preview`` and ``.../adopt``) were
deleted with their dependency sub-router because no browser caller remains.
These guards assert both operations answer 404 and stay out of the generated
OpenAPI contract, while the retained eager health/ping/metrics routes keep
working. Continuity planning itself is unaffected and covered elsewhere.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/crossover-templates/preview",
        "/api/v1/crossover-templates/adopt",
    ],
)
async def test_pruned_crossover_template_returns_404(
    auth_client: AsyncClient, path: str
) -> None:
    """The deleted crossover-template handlers answer 404."""
    response = await auth_client.post(path, json={"source_list_ids": [1]})
    assert response.status_code == 404


def test_pruned_crossover_template_absent_from_openapi() -> None:
    """The pruned crossover-template paths stay out of the OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in (
        "/api/v1/crossover-templates/preview",
        "/api/v1/crossover-templates/adopt",
    ):
        assert path not in schema["paths"], f"{path} must stay pruned"
