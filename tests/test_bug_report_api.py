"""Tests for Bug Report API endpoints."""

import json
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
            data={"title": "Test Bug", "description": "Test description"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_bug_report_description_only(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with title and description only (no screenshot) returns 201."""
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
                data={"title": "Test Bug", "description": "Test description"},
            )

    assert response.status_code == 201
    data = response.json()
    assert "issue_url" in data
    assert data["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["title"] == "Test Bug"
    assert call_kwargs["description"] == "Test description"
    assert call_kwargs["screenshot_bytes"] is None
    assert call_kwargs["screenshot_filename"] is None


@pytest.mark.asyncio
async def test_create_bug_report_with_screenshot(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with title, description, and PNG screenshot returns 201."""
    mock_issue_url = "https://github.com/test/repo/issues/2"
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    # Create minimal PNG bytes (1x1 pixel transparent PNG)
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            files = {"screenshot": ("screenshot.png", png_bytes, "image/png")}
            data = {"title": "Bug with screenshot", "description": "See screenshot"}

            response = await auth_client.post(
                "/api/bug-reports/",
                data=data,
                files=files,
            )

    assert response.status_code == 201
    data = response.json()
    assert data["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["screenshot_bytes"] == png_bytes
    assert call_kwargs["screenshot_filename"] == "screenshot.png"


@pytest.mark.asyncio
async def test_create_bug_report_missing_title(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ without title field returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        data={"description": "Test description"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_missing_description(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ without description field returns 422."""
    response = await auth_client.post(
        "/api/bug-reports/",
        data={"title": "Test Bug"},
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
            data={"title": "Test Bug", "description": "Test description"},
        )

    assert response.status_code == 503
    assert "GitHub integration not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_bug_report_invalid_file_type(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with invalid file type (text/plain) returns 400."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        files = {"screenshot": ("screenshot.txt", b"not an image", "text/plain")}
        data = {"title": "Test Bug", "description": "Test description"}

        response = await auth_client.post(
            "/api/bug-reports/",
            data=data,
            files=files,
        )

    assert response.status_code == 400
    assert "Invalid screenshot type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_bug_report_file_too_large(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with file larger than 5MB returns 400."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        # Create 6MB of zeros
        large_file_bytes = b"\x00" * (6 * 1024 * 1024)

        files = {"screenshot": ("large.png", large_file_bytes, "image/png")}
        data = {"title": "Test Bug", "description": "Test description"}

        response = await auth_client.post(
            "/api/bug-reports/",
            data=data,
            files=files,
        )

    assert response.status_code == 400
    assert "Screenshot too large" in response.json()["detail"]


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
        "screen": {"width": 1920, "height": 1080, "pixelRatio": 1},
        "viewport": {"width": 1920, "height": 1080},
        "scroll": {"x": 0, "y": 0},
        "performance": {"domContentLoaded": 1000, "loadComplete": 2000},
        "errors": [{"message": "test error", "timestamp": "2024-01-01T00:00:00.000Z"}],
    }

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            data = {
                "title": "Bug with diagnostics",
                "description": "See diagnostics",
                "diagnostics": json.dumps(diagnostics_data),
            }

            response = await auth_client.post("/api/bug-reports/", data=data)

    assert response.status_code == 201
    data_json = response.json()
    assert data_json["issue_url"] == mock_issue_url
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

            data = {"title": "Bug without diagnostics", "description": "No diagnostics"}

            response = await auth_client.post("/api/bug-reports/", data=data)

    assert response.status_code == 201
    data_json = response.json()
    assert data_json["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["diagnostics_data"] is None


@pytest.mark.asyncio
async def test_create_bug_report_invalid_diagnostics_json(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with invalid diagnostics JSON returns 400."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        data = {
            "title": "Bug with invalid diagnostics",
            "description": "Invalid JSON",
            "diagnostics": "{{invalid json}}",
        }

        response = await auth_client.post("/api/bug-reports/", data=data)

    assert response.status_code == 400
    assert "Invalid diagnostics JSON" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_bug_report_with_diagnostics_and_screenshot(auth_client: AsyncClient) -> None:
    """POST /api/bug-reports/ with both diagnostics and screenshot returns 201."""
    mock_issue_url = "https://github.com/test/repo/issues/5"
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

    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\x0d\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        with patch(
            "app.api.bug_report.create_bug_report_issue", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_issue_url

            files = {"screenshot": ("screenshot.png", png_bytes, "image/png")}
            data = {
                "title": "Bug with both",
                "description": "Both diagnostics and screenshot",
                "diagnostics": json.dumps(diagnostics_data),
            }

            response = await auth_client.post("/api/bug-reports/", data=data, files=files)

    assert response.status_code == 201
    data_json = response.json()
    assert data_json["issue_url"] == mock_issue_url
    mock_create.assert_called_once()
    call_kwargs = mock_create.call_args.kwargs
    assert call_kwargs["diagnostics_data"] == diagnostics_data
    assert call_kwargs["screenshot_bytes"] == png_bytes
    assert call_kwargs["screenshot_filename"] == "screenshot.png"
