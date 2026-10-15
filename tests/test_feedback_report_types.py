"""Focused coverage for user-selectable feedback report types."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.schemas.bug_report import ReportType
from app.services.github_service import _create_bug_report_issue_sync, _labels_for_report_type
from scripts.factory_eligibility import is_manual_only


def test_report_type_labels_are_distinct() -> None:
    """Bug reports and feature requests receive their canonical labels."""
    assert _labels_for_report_type("bug") == ["bug", "user-reported"]
    assert _labels_for_report_type("feature") == ["enhancement", "user-reported"]


@pytest.mark.parametrize(
    ("report_type", "expected_gate"),
    [("feature", True), ("bug", False)],
)
def test_feedback_issue_execution_gate_matches_report_type(
    report_type: ReportType,
    expected_gate: bool,
) -> None:
    """New feature requests require product approval; ordinary bugs do not."""
    settings = MagicMock()
    settings.github_token = "test-token"
    settings.github_repo_owner = "JoshCLWren"
    settings.github_repo_name = "comic-pile"

    repository = MagicMock()
    repository.create_issue.return_value.html_url = "https://github.com/test/repo/issues/9"
    github_client = MagicMock()
    github_client.get_repo.return_value = repository

    with (
        patch("app.services.github_service.get_github_settings", return_value=settings),
        patch("app.services.github_service.Github", return_value=github_client),
    ):
        url = _create_bug_report_issue_sync(
            report_type=report_type,
            title="QA example",
            description="A user supplied description.",
            username="reader",
        )

    assert url == "https://github.com/test/repo/issues/9"
    kwargs = repository.create_issue.call_args.kwargs
    body = kwargs["body"]
    assert is_manual_only(body) is expected_gate
    assert "A user supplied description." in body
    assert kwargs["labels"] == _labels_for_report_type(report_type)
    marker = "<!-- factory-execution:manual-only -->"
    if expected_gate:
        assert body.startswith(f"{marker}\\n\\n")
        assert body.count(marker) == 1
    else:
        assert marker not in body


@pytest.mark.asyncio
async def test_create_feature_request_routes_selected_type(
    auth_client: AsyncClient, test_username: str
) -> None:
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
        username=test_username,
        diagnostics_data=None,
    )


@pytest.mark.asyncio
async def test_create_report_defaults_to_bug(
    auth_client: AsyncClient, test_username: str
) -> None:
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
        username=test_username,
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
