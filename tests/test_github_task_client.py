"""Tests for GitHub task client."""

import os
import sys
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from github import Issue, Label

sys.path.insert(0, "/home/josh/code/comic-pile")
from scripts.github_task_client import (
    GitHubRateLimitError,
    GitHubTaskClient,
    PRIORITY_LABELS,
    STATUS_LABELS,
)


@pytest.fixture
def mock_github():
    """Mock GitHub client."""
    with patch("scripts.github_task_client.Github") as mock:
        yield mock


@pytest.fixture
def mock_repo():
    """Mock GitHub repository."""
    return MagicMock()


@pytest.fixture
def mock_issue():
    """Mock GitHub issue."""
    issue = MagicMock(spec=Issue.Issue)
    issue.number = 123
    issue.title = "Test Task"
    issue.body = "Test description"
    issue.created_at = datetime.now(UTC)
    issue.updated_at = datetime.now(UTC)
    issue.html_url = "https://github.com/test/repo/issues/123"

    return issue


@pytest.fixture
def github_client(mock_github, mock_repo):
    """Create GitHub task client with mocks."""
    mock_github.return_value.get_repo.return_value = mock_repo
    os.environ["GITHUB_TOKEN"] = "test_token"
    os.environ["GITHUB_REPO"] = "test/repo"

    client = GitHubTaskClient(token="test_token", repo="test/repo")
    return client


class TestGitHubTaskClient:
    """Test GitHub task client functionality."""

    def test_initialization(self):
        """Test client initialization."""
        os.environ["GITHUB_TOKEN"] = "test_token"
        client = GitHubTaskClient(token="test_token", repo="test/repo")
        assert client.token == "test_token"
        assert client.repo_name == "test/repo"

    def test_initialization_without_token(self):
        """Test client initialization without token raises error."""
        os.environ["GITHUB_TOKEN"] = ""
        with pytest.raises(ValueError, match="GITHUB_TOKEN"):
            GitHubTaskClient(token=None, repo="test/repo")

    def test_parse_issue_to_task(self, github_client, mock_issue):
        """Test parsing GitHub issue to task dict."""
        mock_label_pending = MagicMock(spec=Label.Label)
        mock_label_pending.name = STATUS_LABELS["pending"]

        mock_label_high = MagicMock(spec=Label.Label)
        mock_label_high.name = PRIORITY_LABELS["high"]

        mock_label_ralph = MagicMock(spec=Label.Label)
        mock_label_ralph.name = "ralph-task"

        mock_issue.labels = [mock_label_pending, mock_label_high, mock_label_ralph]

        task = github_client._parse_issue_to_task(mock_issue)

        assert task["id"] == 123
        assert task["title"] == "Test Task"
        assert task["description"] == "Test description"
        assert task["status"] == "pending"
        assert task["priority"] == "high"
        assert task["task_type"] == "feature"
        assert task["url"] == "https://github.com/test/repo/issues/123"

    def test_find_pending_task(self, github_client, mock_repo, mock_issue):
        """Test finding pending tasks."""
        mock_issue.labels = [
            MagicMock(name=STATUS_LABELS["pending"]),
            MagicMock(name=PRIORITY_LABELS["high"]),
            MagicMock(name="ralph-task"),
        ]

        mock_repo.get_issues.return_value = [mock_issue]
        mock_repo.get_issue.return_value = mock_issue

        task = github_client.find_pending_task()

        assert task is not None
        assert task["id"] == 123
        assert task["status"] == "pending"

    def test_find_blocked_task(self, github_client, mock_repo, mock_issue):
        """Test finding blocked tasks."""
        mock_issue.labels = [
            MagicMock(name=STATUS_LABELS["blocked"]),
            MagicMock(name=PRIORITY_LABELS["medium"]),
            MagicMock(name="ralph-task"),
        ]

        mock_repo.get_issues.return_value = [mock_issue]

        task = github_client.find_blocked_task()

        assert task is not None
        assert task["status"] == "blocked"

    def test_update_status(self, github_client, mock_repo, mock_issue):
        """Test updating task status."""
        mock_repo.get_issue.return_value = mock_issue

        updated = github_client.update_status(123, "done")

        assert updated is not None
        assert updated["status"] == "done"
        mock_issue.add_to_labels.assert_called_with(STATUS_LABELS["done"])

    def test_update_status_invalid(self, github_client):
        """Test updating with invalid status raises error."""
        with pytest.raises(ValueError, match="Invalid status"):
            github_client.update_status(123, "invalid")

    def test_add_comment(self, github_client, mock_repo, mock_issue):
        """Test adding comment to task."""
        mock_repo.get_issue.return_value = mock_issue

        github_client.add_comment(123, "Test comment")

        mock_issue.create_comment.assert_called_once_with("Test comment")

    def test_get_task(self, github_client, mock_repo, mock_issue):
        """Test getting task by ID."""
        mock_issue.labels = [
            MagicMock(name=STATUS_LABELS["pending"]),
            MagicMock(name=PRIORITY_LABELS["high"]),
            MagicMock(name="ralph-task"),
        ]
        mock_repo.get_issue.return_value = mock_issue

        task = github_client.get_task(123)

        assert task is not None
        assert task["id"] == 123

    def test_create_task(self, github_client, mock_repo, mock_issue):
        """Test creating a new task."""
        mock_repo.create_issue.return_value = mock_issue
        mock_issue.labels = [
            MagicMock(name=STATUS_LABELS["pending"]),
            MagicMock(name=PRIORITY_LABELS["high"]),
            MagicMock(name="ralph-task"),
        ]

        task = github_client.create_task(
            title="New Task",
            description="Test description",
            priority="high",
        )

        assert task is not None
        assert task["title"] == "New Task"
        mock_repo.create_issue.assert_called_once()

    def test_create_task_invalid_priority(self, github_client):
        """Test creating task with invalid priority raises error."""
        with pytest.raises(ValueError, match="Invalid priority"):
            github_client.create_task(
                title="New Task",
                description="Test",
                priority="invalid",
            )

    def test_are_dependencies_resolved_none(self, github_client):
        """Test dependencies are resolved when none."""
        task = {"id": 123, "dependencies": None}
        assert github_client.are_dependencies_resolved(task) is True

    def test_are_dependencies_resolved_none_string(self, github_client):
        """Test dependencies are resolved when 'none'."""
        task = {"id": 123, "dependencies": "none"}
        assert github_client.are_dependencies_resolved(task) is True

    def test_rate_limit_error(self, github_client, mock_repo):
        """Test rate limit error handling."""
        from github import GithubException

        mock_repo.get_issues.side_effect = GithubException(
            status=403, data={"message": "API rate limit exceeded"}
        )

        with pytest.raises(GitHubRateLimitError):
            github_client.find_pending_task()


class TestGitHubLabels:
    """Test GitHub label constants and functions."""

    def test_status_labels(self):
        """Test status labels are defined."""
        assert "pending" in STATUS_LABELS
        assert "in-progress" in STATUS_LABELS
        assert "done" in STATUS_LABELS
        assert "blocked" in STATUS_LABELS
        assert "in-review" in STATUS_LABELS

    def test_priority_labels(self):
        """Test priority labels are defined."""
        assert "critical" in PRIORITY_LABELS
        assert "high" in PRIORITY_LABELS
        assert "medium" in PRIORITY_LABELS
        assert "low" in PRIORITY_LABELS
