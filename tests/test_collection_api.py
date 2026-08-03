"""Regression coverage for the retired Collections API."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/api/v1/collections/", {}),
        ("post", "/api/v1/collections/", {"json": {"name": "Removed"}}),
        ("get", "/api/v1/collections/1", {}),
        ("put", "/api/v1/collections/1", {"json": {"name": "Removed"}}),
        ("patch", "/api/v1/collections/1", {"json": {"position": 1}}),
        ("delete", "/api/v1/collections/1", {}),
    ],
)
async def test_collection_routes_are_retired(
    auth_client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict[str, object],
) -> None:
    """Former collection endpoints fall through to the standard JSON 404."""
    response = await auth_client.request(method, path, **kwargs)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.asyncio
async def test_collection_routes_are_absent_from_openapi(auth_client: AsyncClient) -> None:
    """Collections are no longer advertised as an active API capability."""
    response = await auth_client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert not any(path.startswith("/api/v1/collections") for path in paths)


@pytest.mark.asyncio
async def test_thread_list_rejects_retired_collection_id_query(
    auth_client: AsyncClient,
) -> None:
    """A retired collection_id query parameter fails closed with 422."""
    response = await auth_client.get("/api/threads/", params={"collection_id": 4})

    assert response.status_code == 422
    assert response.json() == {"detail": "collection_id is retired"}


@pytest.mark.asyncio
async def test_roll_request_rejects_retired_collection_id_body(
    auth_client: AsyncClient,
) -> None:
    """A roll body carrying a retired collection_id fails closed with 422."""
    response = await auth_client.post("/api/roll/", json={"collection_id": 4})

    assert response.status_code == 422
