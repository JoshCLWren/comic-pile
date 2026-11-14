"""Pruned Python demo route stays absent; native Rust v2 is kept (#4855).

The Python ``/api/v1/demo/roll`` handler was deleted with its router mount
because no browser caller remains — the JavaScript client calls the native
Rust ``GET /api/v2/demo-roll`` resource. These guards assert the pruned
Python surface answers 404 and stays out of the generated OpenAPI contract.
The retained native Rust v2 guest demo keeps working.
"""

import pytest
from httpx import AsyncClient

from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/demo/roll",
        "/api/demo/roll",
    ],
)
async def test_pruned_python_demo_returns_404(
    client: AsyncClient, path: str
) -> None:
    """The deleted Python demo handler answers 404 on both aliases."""
    response = await client.get(path)
    assert response.status_code == 404


def test_pruned_python_demo_absent_from_openapi() -> None:
    """The pruned Python demo paths stay out of the OpenAPI contract."""
    schema = create_app(serve_frontend=False).openapi()
    for path in ("/api/v1/demo/roll", "/api/demo/roll"):
        assert path not in schema["paths"], f"{path} must stay pruned"
