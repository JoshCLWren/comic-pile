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
    assert call_kwargs["diagnostics_data"] is not None
    from app.schemas.bug_report import BugReportDiagnostics

    assert isinstance(call_kwargs["diagnostics_data"], BugReportDiagnostics)
    dumped = call_kwargs["diagnostics_data"].model_dump()
    assert dumped["timestamp"] == diagnostics_data["timestamp"]
    assert dumped["url"] == diagnostics_data["url"]
    assert dumped["user_agent"] == diagnostics_data["userAgent"]
    assert dumped["screen"]["width"] == diagnostics_data["screen"]["width"]
    assert dumped["screen"]["height"] == diagnostics_data["screen"]["height"]
    assert dumped["screen"]["pixel_ratio"] == float(diagnostics_data["screen"]["pixelRatio"])
    assert dumped["errors"] == diagnostics_data["errors"]


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


@pytest.mark.parametrize(
    "input_str, expected",
    [
        ("no backticks", "no backticks"),
        ("with `backtick` here", "with \\`backtick\\` here"),
        ("```code```", "\\`\\`\\`code\\`\\`\\`"),
        ("", ""),
    ],
)
def test_escape_markdown_code(input_str: str, expected: str) -> None:
    """_escape_markdown_code escapes backticks in strings."""
    from app.services.github_service import _escape_markdown_code

    assert _escape_markdown_code(input_str) == expected


@pytest.mark.asyncio
async def test_create_bug_report_diagnostics_missing_required_fields(
    auth_client: AsyncClient,
) -> None:
    """POST /api/bug-reports/ with missing required diagnostics fields returns 422."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        # Missing 'screen' field
        response = await auth_client.post(
            "/api/bug-reports/",
            json={
                "title": "Bug with partial diagnostics",
                "description": "Missing screen",
                "diagnostics": {
                    "timestamp": "2024-01-01T00:00:00.000Z",
                    "url": "http://test.com",
                    "userAgent": "test-agent",
                    "viewport": {"width": 390, "height": 664},
                    "scroll": {"x": 0, "y": 0},
                    "performance": {},
                    "errors": [],
                },
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_bug_report_diagnostics_wrong_nested_type(
    auth_client: AsyncClient,
) -> None:
    """POST /api/bug-reports/ with wrong nested diagnostics type returns 422."""
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    with patch("app.api.bug_report.get_github_settings") as mock_get_settings:
        mock_get_settings.return_value = mock_settings

        # 'screen' should be a dict, not a string
        response = await auth_client.post(
            "/api/bug-reports/",
            json={
                "title": "Bug with malformed diagnostics",
                "description": "Screen is a string",
                "diagnostics": {
                    "timestamp": "2024-01-01T00:00:00.000Z",
                    "url": "http://test.com",
                    "userAgent": "test-agent",
                    "screen": "bad",
                    "viewport": {"width": 390, "height": 664},
                    "scroll": {"x": 0, "y": 0},
                    "performance": {},
                    "errors": [],
                },
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_github_service_escapes_backticks_in_diagnostics(
    auth_client: AsyncClient,
) -> None:
    """create_bug_report_issue escapes backticks in diagnostic values."""
    mock_issue_url = "https://github.com/test/repo/issues/5"
    mock_settings = MagicMock()
    mock_settings.is_configured = True

    from app.schemas.bug_report import BugReportDiagnostics

    diagnostics_model = BugReportDiagnostics(
        timestamp="2024-01-01T00:00:00.000Z",
        url="http://test.com",
        userAgent="test-agent```injected```",
        screen={"width": 390, "height": 844, "pixelRatio": 3},
        viewport={"width": 390, "height": 664},
        scroll={"x": 0, "y": 0},
        performance={},
        errors=[{"message": "error with `backtick`", "timestamp": "2024-01-01T00:00:00.000Z"}],
    )

    with (
        patch("app.api.bug_report.get_github_settings") as mock_get_settings,
        patch("app.services.github_service.Github") as mock_github,
    ):
        mock_get_settings.return_value = mock_settings
        mock_repo = MagicMock()
        mock_issue = MagicMock()
        mock_issue.html_url = mock_issue_url
        mock_repo.create_issue.return_value = mock_issue
        mock_github.return_value.get_repo.return_value = mock_repo

        response = await auth_client.post(
            "/api/bug-reports/",
            json={
                "title": "Bug with backticks",
                "description": "Testing backtick escaping",
                "diagnostics": diagnostics_model.model_dump(by_alias=True),
            },
        )

    assert response.status_code == 201
    assert response.json()["issue_url"] == mock_issue_url
    mock_repo.create_issue.assert_called_once()
    issue_body = mock_repo.create_issue.call_args.kwargs["body"]
    # Unescaped backticks should NOT appear in diagnostic values
    assert "```injected```" not in issue_body
    assert "error with `backtick`" not in issue_body
    # The Markdown code fence syntax should still be present for error formatting
    assert "```" in issue_body
