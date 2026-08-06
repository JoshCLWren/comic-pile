"""Focused coverage for user-selectable feedback report types."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.services.github_service import _labels_for_report_type


def test_report_type_labels_are_distinct() -> None:
    """Bug reports and feature requests receive their canonical labels."""
    assert _labels_for_report_type("bug") == ["bug", "user-reported"]
    assert _labels_for_report_type("feature") == ["enhancement", "user-reported"]


@pytest.mark.asyncio
async def test_create_feature_request_routes_selected_type(auth_client: AsyncClient) -> None:
    """The API forwards an explicit feature selection to GitHub issue creation."""
    mock_settings = MagicMock(is_configured=True)
    mock_create = AsyncMock(return_value="https://github.com/test/repo/issues/9")

    with (
        patch("app.api.bug_report.get_github_settings", return_value=mock_settings),
        patch("app.api.bug_report.create_bug_report_issue", mock_create),
    ):
        response = await auth_client.post(
            "/api/bug-reports/",
            json={
                "report_type": "feature",
                "title": "Add a reading timer",
                "description": "Let me track time spent reading an issue.",
            },
        )

    assert response.status_code == 201
    assert response.json() == {"issue_url": "https://github.com/test/repo/issues/9"}
    mock_create.assert_awaited_once_with(
        report_type="feature",
        title="Add a reading timer",
        description="Let me track time spent reading an issue.",
        username="testuser",
        diagnostics_data=None,
    )


@pytest.mark.asyncio
async def test_create_report_defaults_to_bug(auth_client: AsyncClient) -> None:
    """Older clients that omit report_type retain bug-report behavior."""
    mock_settings = MagicMock(is_configured=True)
    mock_create = AsyncMock(return_value="https://github.com/test/repo/issues/10")

    with (
        patch("app.api.bug_report.get_github_settings", return_value=mock_settings),
        patch("app.api.bug_report.create_bug_report_issue", mock_create),
    ):
        response = await auth_client.post(
            "/api/bug-reports/",
            json={"title": "Broken button", "description": "The button does nothing."},
        )

    assert response.status_code == 201
    mock_create.assert_awaited_once_with(
        report_type="bug",
        title="Broken button",
        description="The button does nothing.",
        username="testuser",
        diagnostics_data=None,
    )


@pytest.mark.asyncio
async def test_create_report_rejects_unknown_type(auth_client: AsyncClient) -> None:
    """Unknown report types cannot create incorrectly labeled GitHub issues."""
    response = await auth_client.post(
        "/api/bug-reports/",
        json={
            "report_type": "question",
            "title": "How does this work?",
            "description": "This is not a supported report type.",
        },
    )

    assert response.status_code == 422
