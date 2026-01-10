"""Tests for GitHub task client (gh CLI implementation)."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "/home/josh/code/comic-pile")
from scripts.github_task_client import (
    GitHubTaskClient,
    PRIORITY_LABELS,
    STATUS_LABELS,
)


@pytest.fixture
def mock_gh_auth():
    """Mock gh CLI authentication check."""
    with patch("subprocess.run") as mock:
        mock.return_value = MagicMock(returncode=0, stdout="")
        yield mock


@pytest.fixture
def mock_gh_commands():
    """Mock gh CLI commands."""
    with patch("subprocess.run") as mock:

        def side_effect_func(cmd, *args, **kwargs):
            result = MagicMock()

            if ["gh", "auth", "status"] in cmd:
                result.returncode = 0
                result.stdout = ""
            elif ["gh", "issue", "list"] in cmd:
                result.returncode = 0
                result.stdout = "[]"
            elif ["gh", "issue", "view"] in cmd:
                result.returncode = 0
                result.stdout = json.dumps(
                    {
                        "number": 123,
                        "title": "Test Task",
                        "body": "Test description",
                        "labels": [],
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "url": "https://github.com/test/repo/issues/123",
                    }
                )
            else:
                result.returncode = 0
                result.stdout = ""

            return result

        mock.side_effect = side_effect_func
        yield mock


@pytest.fixture
def github_client(mock_gh_commands):
    """Create GitHub task client with mocks."""
    os.environ["GITHUB_REPO"] = "test/repo"
    client = GitHubTaskClient(repo="test/repo")
    return client


class TestGitHubTaskClient:
    """Test GitHub task client functionality."""

    def test_initialization(self, mock_gh_commands):
        """Test client initialization."""
        os.environ["GITHUB_REPO"] = "test/repo"
        client = GitHubTaskClient(repo="test/repo")
        assert client.repo_name == "test/repo"

    def test_parse_issue_to_task(self, github_client):
        """Test parsing GitHub issue JSON to task dict."""
        issue = {
            "number": 123,
            "title": "Test Task",
            "body": "**Type:** feature\n**Priority:** high\n**Dependencies:** none",
            "labels": [
                {"name": STATUS_LABELS["pending"]},
                {"name": PRIORITY_LABELS["high"]},
                {"name": "ralph-task"},
            ],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "url": "https://github.com/test/repo/issues/123",
        }

        task = github_client._parse_issue_to_task(issue)

        assert task["id"] == 123
        assert task["title"] == "Test Task"
        assert (
            task["description"] == "**Type:** feature\n**Priority:** high\n**Dependencies:** none"
        )
        assert task["status"] == "pending"
        assert task["priority"] == "high"
        assert task["task_type"] == "feature"
        assert task["url"] == "https://github.com/test/repo/issues/123"

    def test_parse_issue_with_dependencies(self, github_client):
        """Test parsing issue with dependencies."""
        issue = {
            "number": 456,
            "title": "Task with deps",
            "body": "**Type:** bug\n**Priority:** critical\n**Dependencies:** 123, 124",
            "labels": [
                {"name": STATUS_LABELS["pending"]},
                {"name": PRIORITY_LABELS["critical"]},
                {"name": "ralph-task"},
            ],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "url": "https://github.com/test/repo/issues/456",
        }

        task = github_client._parse_issue_to_task(issue)

        assert task["dependencies"] == "123, 124"
        assert task["task_type"] == "bug"

    def test_extract_field_from_body(self, github_client):
        """Test extracting field from issue body."""
        body = "**Type:** feature\n**Priority:** high\n**Description:** Some text"

        assert github_client._extract_field_from_body(body, "Type") == "feature"
        assert github_client._extract_field_from_body(body, "Priority") == "high"
        assert github_client._extract_field_from_body(body, "Missing") is None
        assert github_client._extract_field_from_body(body, "Missing", "default") == "default"

    def test_find_pending_task_none(self, github_client):
        """Test finding pending tasks when none exist."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="[]")
            task = github_client.find_pending_task()
            assert task is None

    def test_find_pending_task(self, github_client):
        """Test finding pending tasks."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "number": 123,
                            "title": "Test Task",
                            "body": "**Type:** feature\n**Dependencies:** none",
                            "labels": [
                                {"name": STATUS_LABELS["pending"]},
                                {"name": "ralph-task"},
                            ],
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/test/repo/issues/123",
                        }
                    ]
                ),
            )
            task = github_client.find_pending_task()
            assert task is not None
            assert task["id"] == 123
            assert task["status"] == "pending"

    def test_find_blocked_task(self, github_client):
        """Test finding blocked tasks."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "number": 456,
                            "title": "Blocked Task",
                            "body": "**Type:** bug\n**Dependencies:** none",
                            "labels": [
                                {"name": STATUS_LABELS["blocked"]},
                                {"name": "ralph-task"},
                            ],
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/test/repo/issues/456",
                        }
                    ]
                ),
            )
            task = github_client.find_blocked_task()
            assert task is not None
            assert task["status"] == "blocked"

    def test_find_in_review_task(self, github_client):
        """Test finding in-review tasks."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "number": 789,
                            "title": "In Review Task",
                            "body": "**Type:** feature\n**Dependencies:** none",
                            "labels": [
                                {"name": STATUS_LABELS["in-review"]},
                                {"name": "ralph-task"},
                            ],
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/test/repo/issues/789",
                        }
                    ]
                ),
            )
            task = github_client.find_in_review_task()
            assert task is not None
            assert task["status"] == "in-review"

    def test_update_status(self, github_client):
        """Test updating task status."""
        with patch("subprocess.run") as mock:
            call_count = [0]

            def side_effect(cmd, *args, **kwargs):
                call_count[0] += 1
                result = MagicMock(returncode=0)
                cmd_str = " ".join(str(c) for c in cmd)

                if "gh issue view 123" in cmd_str and "labels" in cmd_str:
                    if call_count[0] == 1:
                        result.stdout = json.dumps(
                            {
                                "number": 123,
                                "title": "Test Task",
                                "body": "**Type:** feature\n**Dependencies:** none",
                                "labels": [
                                    {"name": STATUS_LABELS["pending"]},
                                    {"name": "ralph-task"},
                                ],
                                "created_at": "2024-01-01T00:00:00Z",
                                "updated_at": "2024-01-01T00:00:00Z",
                                "url": "https://github.com/test/repo/issues/123",
                            }
                        )
                    else:
                        result.stdout = json.dumps(
                            {
                                "number": 123,
                                "title": "Test Task",
                                "body": "**Type:** feature\n**Dependencies:** none",
                                "labels": [
                                    {"name": STATUS_LABELS["done"]},
                                    {"name": "ralph-task"},
                                ],
                                "created_at": "2024-01-01T00:00:00Z",
                                "updated_at": "2024-01-01T00:00:00Z",
                                "url": "https://github.com/test/repo/issues/123",
                            }
                        )
                else:
                    result.stdout = ""

                return result

            mock.side_effect = side_effect

            updated = github_client.update_status(123, "done")
            assert updated is not None
            assert updated["status"] == "done"

    def test_update_status_invalid(self, github_client):
        """Test updating with invalid status raises error."""
        with pytest.raises(ValueError, match="Invalid status"):
            github_client.update_status(123, "invalid")

    def test_add_comment(self, github_client):
        """Test adding comment to task."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="")
            github_client.add_comment(123, "Test comment")

    def test_get_task(self, github_client):
        """Test getting task by ID."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "number": 123,
                        "title": "Test Task",
                        "body": "**Type:** feature\n**Dependencies:** none",
                        "labels": [
                            {"name": STATUS_LABELS["pending"]},
                            {"name": "ralph-task"},
                        ],
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "url": "https://github.com/test/repo/issues/123",
                    }
                ),
            )
            task = github_client.get_task(123)
            assert task is not None
            assert task["id"] == 123

    def test_create_task(self, github_client):
        """Test creating a new task."""
        with patch("subprocess.run") as mock:

            def side_effect(cmd, *args, **kwargs):
                result = MagicMock(returncode=0)
                cmd_str = " ".join(cmd)

                if "gh issue create" in cmd_str:
                    result.stdout = "https://github.com/test/repo/issues/999\n"
                elif "gh issue view 999" in cmd_str:
                    result.stdout = json.dumps(
                        {
                            "number": 999,
                            "title": "New Task",
                            "body": "**Type:** feature\n**Dependencies:** none",
                            "labels": [
                                {"name": STATUS_LABELS["pending"]},
                                {"name": PRIORITY_LABELS["high"]},
                                {"name": "ralph-task"},
                            ],
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                            "url": "https://github.com/test/repo/issues/999",
                        }
                    )
                else:
                    result.stdout = ""

                return result

            mock.side_effect = side_effect

            task = github_client.create_task(
                title="New Task",
                description="Test description",
                priority="high",
            )

            assert task is not None
            assert task["title"] == "New Task"

    def test_create_task_invalid_priority(self, github_client):
        """Test creating task with invalid priority raises error."""
        with pytest.raises(ValueError, match="Invalid priority"):
            github_client.create_task(
                title="New Task",
                description="Test",
                priority="invalid",
            )

    def test_are_dependencies_resolved_none(self, github_client):
        """Test dependencies are resolved when None."""
        task = {"id": 123, "dependencies": None}
        assert github_client.are_dependencies_resolved(task) is True

    def test_are_dependencies_resolved_none_string(self, github_client):
        """Test dependencies are resolved when 'none'."""
        task = {"id": 123, "dependencies": "none"}
        assert github_client.are_dependencies_resolved(task) is True

    def test_are_dependencies_resolved_not_done(self, github_client):
        """Test dependencies not resolved when dependent task not done."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "number": 456,
                        "title": "Dependent Task",
                        "body": "**Type:** feature\n**Dependencies:** none",
                        "labels": [
                            {"name": STATUS_LABELS["pending"]},
                            {"name": "ralph-task"},
                        ],
                        "created_at": "2024-01-01T00:00:00Z",
                        "updated_at": "2024-01-01T00:00:00Z",
                        "url": "https://github.com/test/repo/issues/456",
                    }
                ),
            )
            task = {"id": 123, "dependencies": "456"}
            assert github_client.are_dependencies_resolved(task) is False

    def test_get_label_color(self, github_client):
        """Test getting label colors."""
        assert github_client._get_label_color("ralph-task") == "7057ff"
        assert github_client._get_label_color("qc-issue") == "d93f0b"
        assert github_client._get_label_color("ralph-status:pending") == "fef2c0"
        assert github_client._get_label_color("ralph-status:done") == "006b75"
        assert github_client._get_label_color("ralph-priority:critical") == "b60205"
        assert github_client._get_label_color("unknown") == "cccccc"

    def test_verify_gh_cli_authenticated(self):
        """Test gh CLI verification when authenticated."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=0, stdout="")
            client = GitHubTaskClient(repo="test/repo")
            assert client.repo_name == "test/repo"

    def test_verify_gh_cli_not_authenticated(self):
        """Test gh CLI verification when not authenticated."""
        with patch("subprocess.run") as mock:
            mock.return_value = MagicMock(returncode=1, stdout="")
            with pytest.raises(ValueError, match="gh CLI not authenticated"):
                GitHubTaskClient(repo="test/repo")

    def test_verify_gh_cli_not_installed(self):
        """Test gh CLI verification when not installed."""
        with patch("subprocess.run") as mock:
            mock.side_effect = FileNotFoundError()
            with pytest.raises(ValueError, match="gh CLI not found"):
                GitHubTaskClient(repo="test/repo")


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

    def test_status_label_formats(self):
        """Test status label formats."""
        assert STATUS_LABELS["pending"] == "ralph-status:pending"
        assert STATUS_LABELS["done"] == "ralph-status:done"
        assert STATUS_LABELS["in-review"] == "ralph-status:in-review"

    def test_priority_label_formats(self):
        """Test priority label formats."""
        assert PRIORITY_LABELS["critical"] == "ralph-priority:critical"
        assert PRIORITY_LABELS["high"] == "ralph-priority:high"
        assert PRIORITY_LABELS["medium"] == "ralph-priority:medium"
        assert PRIORITY_LABELS["low"] == "ralph-priority:low"
