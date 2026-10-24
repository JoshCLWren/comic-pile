"""Regression guards for eliminating synthetic Neon database wakeups."""

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", {"status": "alive"}),
        ("/api/v1/keepalive", {"status": "disabled"}),
    ],
)
async def test_public_probes_do_not_connect_to_database(
    path: str, expected: dict[str, str]
) -> None:
    app = create_app(serve_frontend=False)

    async def forbidden_db() -> AsyncSession:
        raise AssertionError("Public liveness probe must not wake Neon")
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = forbidden_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == expected


def test_frontend_does_not_mount_neon_keepalive() -> None:
    source = (Path(__file__).resolve().parents[1] / "frontend/src/App.tsx").read_text()
    assert "useKeepalive" not in source
