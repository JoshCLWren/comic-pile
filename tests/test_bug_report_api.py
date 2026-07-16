"""Tests for Bug Report API endpoints."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest.mark.asyncio
async def test_create_bug_report_unauthenticated() -> None:
    """POST /api/bug-reports/ without auth header returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/bug-reports/",
            json={"title": "Test Bug", "description": "Test description"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_bug_report_description_only(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with title and description only returns 201."""
    mock_issue_url = "https://github.com/test/repo/issues/1"
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            response = await auth_client.post(
                "/api/bug-reports/",
                json={"title": "Test Bug", "description": "Test description"},
            )

    assert response.status_code == 201
    data = response.json()
    assert "issue_url" in data
    assert data["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["title"] == "Test Bug"
    assert call_kwargs["description"] == "Test description"
    assert call_kwargs["diagnostics_data"] is None


@pytest.mark.asyncio
async def test_create_bug_report_missing_title(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ without title field returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        json={"description": "Test description"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_missing_description(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ without description field returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        json={"title": "Test Bug"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_blank_title(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with blank title returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        json={"title": "   ", "description": "Test description"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_blank_description(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with blank description returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        json={"title": "Test Bug", "description": "   "},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_github_not_configured(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ when GitHub not configured returns 503."""
    mock_settings = MagicMock()
    mock_settings.is_configured = False

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        response = await auth_client.post(
            "/api/bug-reports/",
            json={"title": "Test Bug", "description": "Test description"},
        )

    assert response.status_code == 503
    assert "GitHub integration not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_bug_report_with_diagnostics(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with diagnostics returns 201."""
    mock_issue_url = "https://github.com/test/repo/issues/3"
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    diagnostics_data = {
        "timestamp": "2024-01-01T00:00:00.000Z",
        "url": "http://test.com",
        "userAgent": "test-agent",
        "screen": {"width": 390, "height": 844, "pixelRatio": 3},
        "viewport": {"width": 390, "height": 664},
        "scroll": {"x": 0, "y": 234},
        "performance": {"domContentLoaded": 1234, "loadComplete": 2345},
        "errors": [],
    }

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            response = await auth_client.post(
                "/api/bug-reports/",
                json={
                    "title": "Bug with diagnostics",
                    "description": "See diagnostics",
                    "diagnostics": diagnostics_data,
                },
            )

    assert response.status_code == 201
    data = response.json()
    assert data["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["diagnostics_data"] == diagnostics_data


@pytest.mark.asyncio
async def test_create_bug_report_without_diagnostics(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ without diagnostics returns 201."""
    mock_issue_url = "https://github.com/test/repo/issues/4"
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            response = await auth_client.post(
                "/api/bug-reports/",
                json={"title": "Bug without diagnostics", "description": "No diagnostics"},
            )

    assert response.status_code == 201
    data_json = response.json()
    assert data_json["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["diagnostics_data"] is None


@pytest.mark.asyncio
async def test_create_bug_report_invalid_diagnostics_type(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with non-dict diagnostics returns 422."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        response = await auth_client.post(
            "/api/bug-reports/",
            json={
                "title": "Bug with invalid diagnostics",
                "description": "Invalid diagnostics",
                "diagnostics": "not a dict",
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_title_too_long(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with title exceeding max length returns 422."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        response = await auth_client.post(
            "/api/bug-reports/",
            json={"title": "A" * 201, "description": "Test description"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_description_too_long(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with description exceeding max length returns 422."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        response = await auth_client.post(
            "/api/bug-reports/",
            json={"title": "Test Bug", "description": "D" * 2001},
        )

    assert response.status_code == 422
