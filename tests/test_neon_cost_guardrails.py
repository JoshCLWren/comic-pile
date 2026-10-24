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
    """Neither probe should open the database, even if DB access would fail."""
    app = create_app(serve_frontend=False)

    async def forbidden_db() -> AsyncSession:
        """Fail if a supposedly dependency-free probe uses the database."""
        raise AssertionError("Public liveness probe must not wake Neon")

    app.dependency_overrides[get_db] = forbidden_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path)

    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected_status", "expected"),
    [
        ("/health", 200, {"status": "alive"}),
        ("/health/", 200, {"status": "alive"}),
        ("/api/v1/keepalive", 200, {"status": "disabled"}),
        # The compatibility router has no slash route, so the trailing-slash
        # form is a 404 rather than a redirect. It must still avoid heavy init.
        ("/api/v1/keepalive/", 404, {"detail": "Not Found"}),
    ],
)
async def test_public_probes_skip_cold_heavy_initialization(
    path: str,
    expected_status: int,
    expected: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probes must not run cold heavy initialization, including slash redirects.

    ``tests/conftest.py`` disables request-driven heavy initialization by
    default, which would hide a missing middleware exemption. Opt back into the
    lazy path and fail the request from ``init_database`` so any cold database
    access is observable.
    """
    monkeypatch.setenv("TEST_ENVIRONMENT", "true")
    monkeypatch.setenv("ENABLE_LAZY_HEAVY_INIT_IN_TESTS", "true")

    async def forbidden_init(_environment: str) -> None:
        """Fail when a probe triggers the heavy database initialization path."""
        raise AssertionError("Public liveness probe must not initialize the database")

    monkeypatch.setattr("app.main.init_database", forbidden_init)
    app = create_app(serve_frontend=False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        response = await client.get(path)

    assert response.status_code == expected_status
    assert response.json() == expected


@pytest.mark.asyncio
async def test_non_probe_route_does_run_cold_heavy_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probe exemption is specific: ordinary routes still initialize lazily.

    This control proves the forbidden ``init_database`` replacement really is
    reached on the active lazy-init path, so the probe assertions above cannot
    pass vacuously.
    """
    monkeypatch.setenv("TEST_ENVIRONMENT", "true")
    monkeypatch.setenv("ENABLE_LAZY_HEAVY_INIT_IN_TESTS", "true")
    initialized: list[str] = []

    async def forbidden_init(environment: str) -> None:
        """Record the cold path and refuse to open a database connection."""
        initialized.append(environment)
        raise AssertionError("ordinary route reached cold heavy initialization")

    monkeypatch.setattr("app.main.init_database", forbidden_init)
    app = create_app(serve_frontend=False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        with pytest.raises(AssertionError, match="cold heavy initialization"):
            await client.get("/api/not-a-real-probe")

    assert initialized, "the lazy heavy-init path was never exercised"


def test_frontend_does_not_mount_neon_keepalive() -> None:
    """Authenticated pages must not schedule synthetic database traffic."""
    source = (Path(__file__).resolve().parents[1] / "frontend/src/App.tsx").read_text()
    assert "useKeepalive" not in source
